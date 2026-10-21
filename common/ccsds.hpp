#pragma once

// CCSDS Space Packets (CCSDS 133.0-B): a 6-byte big-endian primary header, a
// 6-byte mission-elapsed-time secondary header (u32 seconds + u16 in 1/65536 s),
// then the user data. Field layouts are listed in docs/icd.md.

#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

namespace ccsds {

inline constexpr uint16_t kApidHousekeeping = 0x10;
inline constexpr uint16_t kApidEstimator = 0x11;  // reserved for stage 3
inline constexpr uint16_t kApidEvents = 0x12;     // events and command acks
inline constexpr uint16_t kApidSimTruth = 0x20;   // SIM-ONLY ground truth, not flight data
inline constexpr uint16_t kApidCommand = 0x30;
inline constexpr size_t kHeaderBytes = 12;  // primary + secondary

struct Header {
  uint16_t apid = 0;
  bool is_command = false;
  uint16_t seq_count = 0;  // 14 bits
  double met_s = 0.0;
};

// Appends big-endian fields.
struct Writer {
  std::vector<uint8_t> bytes;
  void u8(uint8_t v) { bytes.push_back(v); }
  void u16(uint16_t v) { u8(v >> 8), u8(v & 0xFF); }
  void u32(uint32_t v) { u16(v >> 16), u16(v & 0xFFFF); }
  void f32(float v) {
    uint32_t bits;
    std::memcpy(&bits, &v, 4);
    u32(bits);
  }
};

// Reads big-endian fields. Reading past the end returns 0 and clears ok.
struct Reader {
  const uint8_t* data;
  size_t size;
  size_t pos = 0;
  bool ok = true;

  uint8_t u8() {
    if (pos >= size) return ok = false, 0;
    return data[pos++];
  }
  uint16_t u16() {
    uint16_t hi = u8();
    return static_cast<uint16_t>(hi << 8 | u8());
  }
  uint32_t u32() {
    uint32_t hi = u16();
    return hi << 16 | u16();
  }
  float f32() {
    uint32_t bits = u32();
    float v;
    std::memcpy(&v, &bits, 4);
    return v;
  }
  bool done() const { return ok && pos == size; }  // everything read, nothing left
};

inline std::vector<uint8_t> encode(const Header& h, const std::vector<uint8_t>& data) {
  Writer w;
  // Version 0, type, secondary-header flag set, APID.
  w.u16(static_cast<uint16_t>((h.is_command ? 0x1000 : 0) | 0x0800 | (h.apid & 0x7FF)));
  w.u16(static_cast<uint16_t>(0xC000 | (h.seq_count & 0x3FFF)));     // unsegmented
  w.u16(static_cast<uint16_t>(kHeaderBytes - 6 + data.size() - 1));  // data length - 1
  double whole_s = std::floor(h.met_s);
  w.u32(static_cast<uint32_t>(whole_s));
  w.u16(static_cast<uint16_t>((h.met_s - whole_s) * 65536.0));
  w.bytes.insert(w.bytes.end(), data.begin(), data.end());
  return w.bytes;
}

// Returns false for a malformed packet. On success data holds the user data.
inline bool decode(const uint8_t* packet, size_t size, Header& h, std::vector<uint8_t>& data) {
  Reader r{packet, size};
  uint16_t id = r.u16(), seq = r.u16(), length = r.u16();
  uint32_t seconds = r.u32();
  uint16_t subseconds = r.u16();
  bool valid = r.ok && (id >> 13) == 0 && (id & 0x0800) && size == 6u + length + 1;
  if (!valid) return false;
  h = {static_cast<uint16_t>(id & 0x7FF), (id & 0x1000) != 0, static_cast<uint16_t>(seq & 0x3FFF),
       seconds + subseconds / 65536.0};
  data.assign(packet + kHeaderBytes, packet + size);
  return true;
}

}  // namespace ccsds
