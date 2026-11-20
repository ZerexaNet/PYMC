// ============================================================
// PyMC - block state table (from world/blocks.json, minecraft-data format)
//
// State ids enumerate properties with the LAST property varying fastest and
// booleans ordered true,false - the same order as world/chunk_io.py.
// ============================================================
#pragma once

#include <cstdint>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include "../worldgen/json.h"

namespace vrs {

struct Prop {
    std::string name;
    std::vector<std::string> values;
    int stride = 1;
};

struct BlockInfo {
    std::string name;          // with "minecraft:" prefix
    std::string short_name;    // without
    int id = 0;                // block registry id
    int min_state = 0, max_state = 0, default_state = 0;
    std::vector<Prop> props;
    bool full = false;         // boundingBox == block
    bool transparent = false;
    bool empty_box = false;    // boundingBox == empty
    int filter_light = 15;     // blocks.json filterLight: light level lost passing through (15 = opaque)
    int emit_light = 0;        // blocks.json emitLight
    float hardness = 0.f;
    float resistance = 0.f;
    std::vector<int> harvest_tools;
};

class BlockTable {
public:
    std::vector<BlockInfo> blocks;
    std::vector<int32_t> block_of_state;          // state -> index into blocks
    std::unordered_map<std::string, int> by_name; // "minecraft:x" -> index

    bool load(const std::string& path) {
        std::ifstream f(path, std::ios::binary);
        if (!f.good()) return false;
        std::stringstream ss;
        ss << f.rdbuf();
        vgen::Json root = vgen::JsonParser(ss.str()).parse();
        int max_state = 0;
        for (size_t i = 0; i < root.size(); i++) {
            const vgen::Json& b = root[i];
            BlockInfo info;
            info.short_name = b.get_str("name");
            info.name = "minecraft:" + info.short_name;
            info.id = (int)b.get("id", 0);
            info.min_state = (int)b.get("minStateId", 0);
            info.max_state = (int)b.get("maxStateId", 0);
            info.default_state = (int)b.get("defaultState", info.min_state);
            std::string box = b.get_str("boundingBox");
            info.full = box == "block";
            info.empty_box = box == "empty";
            info.transparent = b.get_bool("transparent", false);
            info.hardness = b.has("hardness") && b["hardness"].kind == vgen::Json::Number ? (float)b["hardness"].num : 0.f;
            info.resistance = b.has("resistance") && b["resistance"].kind == vgen::Json::Number ? (float)b["resistance"].num : 0.f;
            info.filter_light = b.has("filterLight") && b["filterLight"].kind == vgen::Json::Number ? (int)b["filterLight"].num : 15;
            info.emit_light = b.has("emitLight") && b["emitLight"].kind == vgen::Json::Number ? (int)b["emitLight"].num : 0;
            if (b.has("harvestTools") && b["harvestTools"].is_object())
                for (auto& kv : b["harvestTools"].obj) info.harvest_tools.push_back(std::atoi(kv.first.c_str()));
            if (b.has("states") && b["states"].is_array()) {
                const vgen::Json& states = b["states"];
                for (size_t k = 0; k < states.size(); k++) {
                    Prop p;
                    p.name = states[k].get_str("name");
                    if (states[k].get_str("type") == "bool") {
                        p.values = {"true", "false"};
                    } else if (states[k].has("values")) {
                        const vgen::Json& vals = states[k]["values"];
                        for (size_t v = 0; v < vals.size(); v++) p.values.push_back(vals[v].str);
                    }
                    if (!p.values.empty()) info.props.push_back(p);
                }
                int stride = 1;
                for (int k = (int)info.props.size() - 1; k >= 0; k--) {
                    info.props[k].stride = stride;
                    stride *= (int)info.props[k].values.size();
                }
            }
            if (info.max_state > max_state) max_state = info.max_state;
            by_name[info.name] = (int)blocks.size();
            blocks.push_back(std::move(info));
        }
        block_of_state.assign(max_state + 1, 0);
        for (size_t i = 0; i < blocks.size(); i++)
            for (int s = blocks[i].min_state; s <= blocks[i].max_state; s++) block_of_state[s] = (int32_t)i;
        return true;
    }

    const BlockInfo& info(int state) const {
        if (state < 0 || state >= (int)block_of_state.size()) return blocks[0];
        return blocks[block_of_state[state]];
    }
    int block_index(int state) const {
        if (state < 0 || state >= (int)block_of_state.size()) return 0;
        return block_of_state[state];
    }
    int index_of(const std::string& name) const {
        auto it = by_name.find(name);
        return it == by_name.end() ? -1 : it->second;
    }
    int default_state(const std::string& name) const {
        int i = index_of(name);
        return i < 0 ? 0 : blocks[i].default_state;
    }

    // value index of a property, -1 when the block has no such property
    int prop_index(int state, const char* key) const {
        const BlockInfo& b = info(state);
        for (const Prop& p : b.props)
            if (p.name == key) return ((state - b.min_state) / p.stride) % (int)p.values.size();
        return -1;
    }
    const std::string& prop(int state, const char* key) const {
        static const std::string empty;
        const BlockInfo& b = info(state);
        for (const Prop& p : b.props)
            if (p.name == key) return p.values[((state - b.min_state) / p.stride) % (int)p.values.size()];
        return empty;
    }
    bool is(int state, const char* key, const char* value) const { return prop(state, key) == value; }
    bool has_prop(int state, const char* key) const { return prop_index(state, key) >= 0; }
    int prop_int(int state, const char* key, int def = 0) const {
        const std::string& v = prop(state, key);
        return v.empty() ? def : std::atoi(v.c_str());
    }
    // same block with one property changed (unknown property/value: unchanged)
    int with(int state, const char* key, const std::string& value) const {
        const BlockInfo& b = info(state);
        for (const Prop& p : b.props) {
            if (p.name != key) continue;
            int cur = ((state - b.min_state) / p.stride) % (int)p.values.size();
            for (int v = 0; v < (int)p.values.size(); v++)
                if (p.values[v] == value) return state + (v - cur) * p.stride;
            return state;
        }
        return state;
    }
    int with(int state, const char* key, bool value) const { return with(state, key, std::string(value ? "true" : "false")); }
    int with(int state, const char* key, int value) const { return with(state, key, std::to_string(value)); }
    int with(int state, const char* key, const char* value) const { return with(state, key, std::string(value)); }
};

}  // namespace vrs
