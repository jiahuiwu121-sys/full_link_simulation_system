#ifndef RAMULATOR_BASE_STATS_H
#define RAMULATOR_BASE_STATS_H

#include <functional>
#include <ostream>
#include <string>
#include <type_traits>
#include <vector>

#include "ramulator/base/config_node.h"

namespace Ramulator {

class Stats {
  struct Entry {
    std::string name;
    std::function<void(std::ostream&, int)> printer;
    std::function<ConfigNode()> value;
  };
  std::vector<Entry> m_entries;

  template <typename T>
  static void print_value(std::ostream& os, const T& value) {
    if constexpr (std::is_floating_point_v<T>) {
      os << config_float_string(value);
    } else {
      os << value;
    }
  }

 public:
  // Note: add() captures `ref` by reference. The referenced object must outlive
  // this Stats instance (i.e., stats must be collected before the owner is destroyed).
  template <typename T>
  void add(std::string name, const T& ref) {
    m_entries.push_back(
        {name,
         [n = name, &ref](std::ostream& os, int indent) {
           os << std::string(indent, ' ') << n << ": ";
           print_value(os, ref);
           os << "\n";
         },
         [&ref]() -> ConfigNode { return ConfigNode(ref); }});
  }

  template <typename T>
  void add(std::string name, const std::vector<T>& ref) {
    m_entries.push_back({name,
                         [n = name, &ref](std::ostream& os, int indent) {
                           std::string pad(indent, ' ');
                           os << pad << n << ":\n";
                           for (const auto& v : ref) {
                             os << pad << "  - ";
                             print_value(os, v);
                             os << "\n";
                           }
                         },
                         [&ref]() -> ConfigNode {
                           ConfigNode seq;
                           for (const auto& v : ref) {
                             seq.push_back(ConfigNode(v));
                           }
                           return seq;
                         }});
  }

  void print(std::ostream& os, int indent) const {
    for (const auto& e : m_entries) {
      e.printer(os, indent);
    }
  }

  ConfigNode::Map collect() const {
    ConfigNode::Map map;
    for (const auto& e : m_entries) {
      map[e.name] = e.value();
    }
    return map;
  }

  bool empty() const {
    return m_entries.empty();
  }
};

}  // namespace Ramulator

#endif  // RAMULATOR_BASE_STATS_H
