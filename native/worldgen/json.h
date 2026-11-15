// ============================================================
// PyMC - Minimal JSON reader (for world/data/worldgen_overworld.json)
// ============================================================
#pragma once

#include <cstdlib>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace vgen {

struct Json {
    enum Kind { Null, Bool, Number, String, Array, Object } kind = Null;
    bool b = false;
    double num = 0.0;
    std::string str;
    std::vector<Json> arr;
    std::map<std::string, Json> obj;

    bool is_object() const { return kind == Object; }
    bool is_array() const { return kind == Array; }
    bool is_number() const { return kind == Number; }
    bool is_string() const { return kind == String; }
    bool has(const std::string& k) const { return kind == Object && obj.count(k) > 0; }

    const Json& operator[](const std::string& k) const {
        auto it = obj.find(k);
        if (it == obj.end()) throw std::runtime_error("missing JSON key: " + k);
        return it->second;
    }
    const Json& operator[](size_t i) const { return arr.at(i); }
    size_t size() const { return kind == Array ? arr.size() : obj.size(); }

    double as_double(double def = 0.0) const {
        if (kind == Number) return num;
        if (kind == Bool) return b ? 1.0 : 0.0;
        return def;
    }
    int as_int(int def = 0) const { return kind == Number ? (int)num : def; }
    bool as_bool(bool def = false) const { return kind == Bool ? b : (kind == Number ? num != 0.0 : def); }
    double get(const std::string& k, double def) const { return has(k) ? (*this)[k].as_double(def) : def; }
    bool get_bool(const std::string& k, bool def) const { return has(k) ? (*this)[k].as_bool(def) : def; }
    std::string get_str(const std::string& k, const std::string& def = "") const {
        return has(k) && (*this)[k].kind == String ? (*this)[k].str : def;
    }
};

class JsonParser {
public:
    explicit JsonParser(const std::string& text) : s(text) {}

    Json parse() {
        Json v = value();
        ws();
        if (i != s.size()) throw std::runtime_error("trailing data in JSON");
        return v;
    }

private:
    const std::string& s;
    size_t i = 0;

    void ws() { while (i < s.size() && (s[i] == ' ' || s[i] == '\n' || s[i] == '\r' || s[i] == '\t')) i++; }
    char peek() { ws(); if (i >= s.size()) throw std::runtime_error("unexpected end of JSON"); return s[i]; }
    void expect(char c) { if (peek() != c) throw std::runtime_error(std::string("expected '") + c + "' in JSON"); i++; }

    Json value() {
        char c = peek();
        Json v;
        if (c == '{') {
            v.kind = Json::Object;
            i++;
            if (peek() == '}') { i++; return v; }
            while (true) {
                std::string key = string_lit();
                expect(':');
                v.obj.emplace(std::move(key), value());
                char d = peek();
                i++;
                if (d == '}') break;
                if (d != ',') throw std::runtime_error("expected ',' in JSON object");
            }
        } else if (c == '[') {
            v.kind = Json::Array;
            i++;
            if (peek() == ']') { i++; return v; }
            while (true) {
                v.arr.push_back(value());
                char d = peek();
                i++;
                if (d == ']') break;
                if (d != ',') throw std::runtime_error("expected ',' in JSON array");
            }
        } else if (c == '"') {
            v.kind = Json::String;
            v.str = string_lit();
        } else if (s.compare(i, 4, "true") == 0) {
            v.kind = Json::Bool; v.b = true; i += 4;
        } else if (s.compare(i, 5, "false") == 0) {
            v.kind = Json::Bool; v.b = false; i += 5;
        } else if (s.compare(i, 4, "null") == 0) {
            i += 4;
        } else {
            v.kind = Json::Number;
            const char* start = s.c_str() + i;
            char* end = nullptr;
            v.num = std::strtod(start, &end);
            if (end == start) throw std::runtime_error("bad JSON number");
            i += (size_t)(end - start);
        }
        return v;
    }

    std::string string_lit() {
        expect('"');
        std::string out;
        while (i < s.size() && s[i] != '"') {
            if (s[i] == '\\') {
                i++;
                char e = s[i++];
                switch (e) {
                    case 'n': out += '\n'; break;
                    case 't': out += '\t'; break;
                    case 'r': out += '\r'; break;
                    case 'b': out += '\b'; break;
                    case 'f': out += '\f'; break;
                    case 'u': {
                        unsigned cp = (unsigned)std::strtoul(s.substr(i, 4).c_str(), nullptr, 16);
                        i += 4;
                        if (cp < 0x80) out += (char)cp;
                        else if (cp < 0x800) { out += (char)(0xC0 | (cp >> 6)); out += (char)(0x80 | (cp & 0x3F)); }
                        else { out += (char)(0xE0 | (cp >> 12)); out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F)); }
                        break;
                    }
                    default: out += e;
                }
            } else {
                out += s[i++];
            }
        }
        i++;
        return out;
    }
};

}  // namespace vgen
