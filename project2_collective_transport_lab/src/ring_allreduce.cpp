// A small TCP implementation of ring reduce-scatter followed by all-gather.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
constexpr std::uint32_t kMagic = 0x48534e31;  // "HSN1"
constexpr int kConnectTimeoutSeconds = 10;
constexpr int kIoTimeoutSeconds = 15;

struct Options {
  int rank = -1;
  int world_size = 0;
  int base_port = 28000;
  std::size_t elements = 11;
};

struct SocketPair {
  int outgoing = -1;
  int incoming = -1;
};

struct Bounds {
  std::size_t begin;
  std::size_t end;
};

enum class Phase : std::uint32_t { kReduceScatter = 1, kAllGather = 2 };

std::uint64_t host_to_be64(std::uint64_t value) {
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
  return (static_cast<std::uint64_t>(htonl(static_cast<std::uint32_t>(value))) << 32) |
         htonl(static_cast<std::uint32_t>(value >> 32));
#else
  return value;
#endif
}

std::uint64_t be64_to_host(std::uint64_t value) { return host_to_be64(value); }

void send_all(int fd, const void* data, std::size_t size) {
  const auto* bytes = static_cast<const unsigned char*>(data);
  std::size_t sent = 0;
  while (sent < size) {
#ifdef MSG_NOSIGNAL
    constexpr int flags = MSG_NOSIGNAL;
#else
    constexpr int flags = 0;
#endif
    const ssize_t result = ::send(fd, bytes + sent, size - sent, flags);
    if (result < 0 && errno == EINTR) continue;
    if (result <= 0) throw std::runtime_error("TCP send failed");
    sent += static_cast<std::size_t>(result);
  }
}

void receive_all(int fd, void* data, std::size_t size) {
  auto* bytes = static_cast<unsigned char*>(data);
  std::size_t received = 0;
  while (received < size) {
    const ssize_t result = ::recv(fd, bytes + received, size - received, 0);
    if (result < 0 && errno == EINTR) continue;
    if (result <= 0) throw std::runtime_error("TCP peer closed before the frame was complete");
    received += static_cast<std::size_t>(result);
  }
}

void set_timeouts(int fd) {
  timeval timeout{};
  timeout.tv_sec = kIoTimeoutSeconds;
  if (::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0 ||
      ::setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) != 0) {
    throw std::runtime_error("unable to configure socket timeouts");
  }
}

int create_listener(int port) {
  const int fd = ::socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) throw std::runtime_error("unable to create listener socket");
  int reuse = 1;
  ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  address.sin_port = htons(static_cast<std::uint16_t>(port));
  if (::bind(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0 ||
      ::listen(fd, 1) != 0) {
    ::close(fd);
    throw std::runtime_error("unable to bind rank listener; choose a free port block");
  }
  return fd;
}

int connect_with_retry(int port) {
  const auto deadline = std::chrono::steady_clock::now() +
                        std::chrono::seconds(kConnectTimeoutSeconds);
  while (std::chrono::steady_clock::now() < deadline) {
    const int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) throw std::runtime_error("unable to create outgoing socket");
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons(static_cast<std::uint16_t>(port));
    if (::connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0) {
      set_timeouts(fd);
      return fd;
    }
    ::close(fd);
    std::this_thread::sleep_for(std::chrono::milliseconds(40));
  }
  throw std::runtime_error("timed out connecting to the next rank");
}

SocketPair connect_ring(const Options& options) {
  if (options.world_size == 1) return {};
  const int listener = create_listener(options.base_port + options.rank);
  const int next_rank = (options.rank + 1) % options.world_size;
  const int previous_rank = (options.rank + options.world_size - 1) % options.world_size;
  int outgoing = -1;
  int incoming = -1;
  try {
    outgoing = connect_with_retry(options.base_port + next_rank);
    incoming = ::accept(listener, nullptr, nullptr);
    if (incoming < 0) throw std::runtime_error("unable to accept the previous rank");
    set_timeouts(incoming);
  } catch (...) {
    if (outgoing >= 0) ::close(outgoing);
    if (incoming >= 0) ::close(incoming);
    ::close(listener);
    throw;
  }
  ::close(listener);
  (void)previous_rank;  // documents the expected predecessor in the ring topology
  return {outgoing, incoming};
}

Bounds chunk_bounds(std::size_t elements, int world_size, int chunk) {
  const auto p = static_cast<std::size_t>(world_size);
  const auto i = static_cast<std::size_t>(chunk);
  return {i * elements / p, (i + 1) * elements / p};
}

std::size_t send_chunk(int fd, Phase phase, int step, int chunk,
                       const std::vector<double>& values, Bounds bounds) {
  const std::uint32_t count = static_cast<std::uint32_t>(bounds.end - bounds.begin);
  std::array<std::uint32_t, 5> header = {
      htonl(kMagic), htonl(static_cast<std::uint32_t>(phase)),
      htonl(static_cast<std::uint32_t>(step)), htonl(static_cast<std::uint32_t>(chunk)),
      htonl(count)};
  std::vector<unsigned char> frame(sizeof(header) + static_cast<std::size_t>(count) * sizeof(double));
  std::memcpy(frame.data(), header.data(), sizeof(header));
  std::size_t offset = sizeof(header);
  for (std::size_t index = bounds.begin; index < bounds.end; ++index) {
    std::uint64_t bits = 0;
    std::memcpy(&bits, &values[index], sizeof(bits));
    bits = host_to_be64(bits);
    std::memcpy(frame.data() + offset, &bits, sizeof(bits));
    offset += sizeof(bits);
  }
  send_all(fd, frame.data(), frame.size());
  return frame.size();
}

void receive_chunk(int fd, Phase phase, int step, int chunk,
                   std::vector<double>& values, Bounds bounds) {
  std::array<std::uint32_t, 5> header{};
  receive_all(fd, header.data(), sizeof(header));
  const auto magic = ntohl(header[0]);
  const auto actual_phase = ntohl(header[1]);
  const auto actual_step = ntohl(header[2]);
  const auto actual_chunk = ntohl(header[3]);
  const auto actual_count = ntohl(header[4]);
  const auto expected_count = static_cast<std::uint32_t>(bounds.end - bounds.begin);
  if (magic != kMagic || actual_phase != static_cast<std::uint32_t>(phase) ||
      actual_step != static_cast<std::uint32_t>(step) ||
      actual_chunk != static_cast<std::uint32_t>(chunk) || actual_count != expected_count) {
    throw std::runtime_error("received a frame with an invalid header");
  }
  std::vector<unsigned char> payload(static_cast<std::size_t>(actual_count) * sizeof(double));
  if (!payload.empty()) receive_all(fd, payload.data(), payload.size());
  std::size_t offset = 0;
  for (std::size_t index = bounds.begin; index < bounds.end; ++index) {
    std::uint64_t bits = 0;
    std::memcpy(&bits, payload.data() + offset, sizeof(bits));
    offset += sizeof(bits);
    bits = be64_to_host(bits);
    double value = 0;
    std::memcpy(&value, &bits, sizeof(value));
    values[index] = value;
  }
}

void exchange(int outgoing, int incoming, Phase phase, int step, int send_index,
              int receive_index, std::vector<double>& values, Bounds send_bounds,
              Bounds receive_bounds, std::size_t& bytes_sent) {
  std::exception_ptr send_failure;
  std::size_t frame_bytes = 0;
  std::thread sender([&]() {
    try {
      frame_bytes = send_chunk(outgoing, phase, step, send_index, values, send_bounds);
    } catch (...) {
      send_failure = std::current_exception();
    }
  });
  try {
    receive_chunk(incoming, phase, step, receive_index, values, receive_bounds);
  } catch (...) {
    sender.join();
    throw;
  }
  sender.join();
  if (send_failure) std::rethrow_exception(send_failure);
  bytes_sent += frame_bytes;
}

void allreduce(const Options& options, std::vector<double>& values,
               const SocketPair& sockets, std::size_t& bytes_sent) {
  const int rank = options.rank;
  const int world = options.world_size;
  for (int step = 0; step < world - 1; ++step) {
    const int send_index = (rank - step + world) % world;
    const int receive_index = (rank - step - 1 + world) % world;
    const Bounds send_bounds = chunk_bounds(values.size(), world, send_index);
    const Bounds receive_bounds = chunk_bounds(values.size(), world, receive_index);
    std::vector<double> partial(receive_bounds.end - receive_bounds.begin);
    for (std::size_t offset = 0; offset < partial.size(); ++offset) {
      partial[offset] = values[receive_bounds.begin + offset];
    }
    exchange(sockets.outgoing, sockets.incoming, Phase::kReduceScatter, step,
             send_index, receive_index, values, send_bounds, receive_bounds, bytes_sent);
    for (std::size_t offset = 0; offset < partial.size(); ++offset) {
      values[receive_bounds.begin + offset] += partial[offset];
    }
  }
  for (int step = 0; step < world - 1; ++step) {
    const int send_index = (rank - step + 1 + world) % world;
    const int receive_index = (rank - step + world) % world;
    const Bounds send_bounds = chunk_bounds(values.size(), world, send_index);
    const Bounds receive_bounds = chunk_bounds(values.size(), world, receive_index);
    exchange(sockets.outgoing, sockets.incoming, Phase::kAllGather, step,
             send_index, receive_index, values, send_bounds, receive_bounds, bytes_sent);
  }
}

std::size_t parse_size(const std::string& text, const std::string& name) {
  if (text.empty() || text.front() == '-') {
    throw std::invalid_argument("invalid value for " + name);
  }
  std::size_t used = 0;
  const unsigned long long value = std::stoull(text, &used);
  if (used != text.size()) throw std::invalid_argument("invalid value for " + name);
  return static_cast<std::size_t>(value);
}

int parse_int(const std::string& text, const std::string& name) {
  const std::size_t value = parse_size(text, name);
  if (value > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
    throw std::invalid_argument("value is too large for " + name);
  }
  return static_cast<int>(value);
}

Options parse_options(int argc, char** argv) {
  Options options;
  for (int i = 1; i < argc; ++i) {
    const std::string flag = argv[i];
    if (flag == "--help") {
      std::cout << "Usage: ring_allreduce --rank N --world-size P [--base-port N] [--elements N]\n";
      std::exit(0);
    }
    if (i + 1 >= argc) throw std::invalid_argument("missing value after " + flag);
    const std::string value = argv[++i];
    if (flag == "--rank") options.rank = parse_int(value, flag);
    else if (flag == "--world-size") options.world_size = parse_int(value, flag);
    else if (flag == "--base-port") options.base_port = parse_int(value, flag);
    else if (flag == "--elements") options.elements = parse_size(value, flag);
    else throw std::invalid_argument("unknown option: " + flag);
  }
  if (options.world_size < 1 || options.world_size > 64) {
    throw std::invalid_argument("world size must be between 1 and 64");
  }
  if (options.rank < 0 || options.rank >= options.world_size) {
    throw std::invalid_argument("rank must be within the world size");
  }
  if (options.elements == 0 || options.elements > 1'000'000) {
    throw std::invalid_argument("element count must be between 1 and 1000000");
  }
  if (options.base_port < 1024 ||
      options.base_port + options.world_size - 1 > 65535) {
    throw std::invalid_argument("base port block must fit within ports 1024 to 65535");
  }
  return options;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    const Options options = parse_options(argc, argv);
    std::vector<double> values(options.elements, static_cast<double>(options.rank + 1));
    const SocketPair sockets = connect_ring(options);
    std::size_t bytes_sent = 0;
    const auto start = std::chrono::steady_clock::now();
    allreduce(options, values, sockets, bytes_sent);
    const auto stop = std::chrono::steady_clock::now();
    if (sockets.outgoing >= 0) ::close(sockets.outgoing);
    if (sockets.incoming >= 0) ::close(sockets.incoming);
    const auto elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(stop - start).count();
    double checksum = 0;
    for (double value : values) checksum += value;
    std::cout << "{\"rank\":" << options.rank
              << ",\"world_size\":" << options.world_size
              << ",\"elements\":" << values.size()
              << ",\"first_value\":" << values.front()
              << ",\"last_value\":" << values.back()
              << ",\"checksum\":" << checksum
              << ",\"elapsed_us\":" << elapsed_us
              << ",\"bytes_sent\":" << bytes_sent << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << '\n';
    return 2;
  }
}
