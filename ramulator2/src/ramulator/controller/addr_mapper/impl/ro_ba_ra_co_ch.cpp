#include "ramulator/controller/addr_mapper/i_addr_mapper.h"
#include "ramulator/controller/addr_mapper/addr_mapper_base.h"

#include <stdexcept>
#include <vector>

namespace Ramulator {

// Row-Bank-Rank-Column-Channel (MSB to LSB in original scheme)
class RoBaRaCoCh : public IAddrMapper, public AddrMapperBase {
  RAMULATOR_REGISTER_IMPLEMENTATION_DERIVED(IAddrMapper, RoBaRaCoCh, AddrMapperBase, "RoBaRaCoCh")
  void init() override;
  void apply(Request& req) override;

 private:
  std::vector<int> m_level_sizes;
  int m_internal_prefetch_size = -1;
};

void RoBaRaCoCh::init() {
  AddrMapperBase::init();

  const auto& dram_spec = *m_ctrl->m_device.m_spec;
  const auto& level_sizes = dram_spec.organization.level_sizes;
  m_level_sizes.assign(level_sizes.begin() + 1, level_sizes.end());
  m_internal_prefetch_size = dram_spec.internal_prefetch_size;

  if (m_level_sizes[m_col_idx] <= 0 || m_internal_prefetch_size <= 0 ||
      m_level_sizes[m_col_idx] % m_internal_prefetch_size != 0) {
    throw std::runtime_error("RoBaRaCoCh requires a positive column count divisible by the internal prefetch size");
  }
  for (int size : m_level_sizes) {
    if (size <= 0) {
      throw std::runtime_error("RoBaRaCoCh requires positive DRAM organization level sizes");
    }
  }
}

void RoBaRaCoCh::apply(Request& req) {
  req.addr_vec.resize(m_num_mapped_levels + 1, -1);
  Addr_t addr = req.intra_channel_addr >> m_tx_offset;

  // Mixed-radix extraction is equivalent to bit slicing for power-of-two
  // organizations and also maps exact 24 Gb geometries (whose row count is
  // not a power of two) without silently dropping capacity.
  auto extract_level = [&addr](int radix) {
    const int value = static_cast<int>(addr % radix);
    addr /= radix;
    return value;
  };

  // Column at LSB
  req.addr_vec[m_col_idx + 1] = extract_level(m_level_sizes[m_col_idx] / m_internal_prefetch_size);
  // Pseudochannel through Row (levels 0 to row_idx in organization order)
  for (int i = 0; i <= m_row_idx; i++) {
    req.addr_vec[i + 1] = extract_level(m_level_sizes[i]);
  }
}

}  // namespace Ramulator
