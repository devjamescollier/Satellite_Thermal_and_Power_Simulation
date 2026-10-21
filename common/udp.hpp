#pragma once

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cstdint>
#include <stdexcept>
#include <string>

// Minimal UDP socket on the loopback interface.
class UdpSocket {
 public:
  explicit UdpSocket(int bind_port = 0) : fd_(socket(AF_INET, SOCK_DGRAM, 0)) {
    if (fd_ < 0) throw std::runtime_error("socket() failed");
    if (bind_port == 0) return;
    sockaddr_in addr = loopback(bind_port);
    if (bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof addr) < 0) {
      close(fd_);
      throw std::runtime_error("cannot bind UDP port " + std::to_string(bind_port));
    }
  }
  ~UdpSocket() { close(fd_); }
  UdpSocket(const UdpSocket&) = delete;
  UdpSocket& operator=(const UdpSocket&) = delete;

  void send_to(int port, const void* data, size_t size) const {
    sockaddr_in addr = loopback(port);
    sendto(fd_, data, size, 0, reinterpret_cast<sockaddr*>(&addr), sizeof addr);
  }

  // Waits up to timeout_s for a datagram. Returns its size, or -1 on timeout.
  long receive(void* buf, size_t size, double timeout_s) const {
    pollfd p{fd_, POLLIN, 0};
    if (poll(&p, 1, static_cast<int>(timeout_s * 1000.0)) <= 0) return -1;
    return recv(fd_, buf, size, 0);
  }

 private:
  static sockaddr_in loopback(int port) {
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<uint16_t>(port));
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    return addr;
  }
  int fd_;
};
