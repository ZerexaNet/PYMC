// ============================================================
// PyMC - Paper Plugin Compatibility Layer: Minimal JVM Bridge
//
// Provides a minimal JNI-based JVM that can load .jar plugins
// and bridge Java Bukkit API calls to C++ PYMC API calls.
//
// Architecture:
//   JVMBridge
//     ├── JVM initialization (JNI_CreateJavaVM)
//     ├── Class loading from .jar files
//     ├── Method invocation (static + instance)
//     ├── Field access (static + instance)
//     └── Callback registration (Java→C++ event listeners)
//
// Threading model:
//   - The JVM runs on its own thread(s)
//   - PYMC server thread communicates via the bridge
//   - Event callbacks are marshalled from Java→C++ via JNI
//   - API calls are marshalled from C++→Java via JNI
//
// Class path:
//   The bridge sets up a custom ClassLoader that can load
//   classes from:
//     1. Bukkit API stubs (shipped with PYMC)
//     2. Plugin .jar files
//     3. Paper API compatibility layer
// ============================================================

#ifndef PYMC_JVM_BRIDGE_H
#define PYMC_JVM_BRIDGE_H

#include <string>
#include <vector>
#include <map>
#include <unordered_map>
#include <memory>
#include <functional>
#include <mutex>
#include <cstdint>
#include <optional>

// Forward-declare JNI types to avoid requiring jni.h in this header
// Users must have JDK installed to actually build with JNI support
struct JNIEnv_;
struct _jobject;
struct _jclass;
struct _jmethodID;
struct _jfieldID;
struct JavaVM_;

using JNIEnv = JNIEnv_;
using jobject = _jobject*;
using jclass = _jclass*;
using jmethodID = _jmethodID*;
using jfieldID = _jfieldID*;
using JavaVM = JavaVM_;

// JNI primitive types
using jboolean = uint8_t;
using jbyte = int8_t;
using jchar = uint16_t;
using jshort = int16_t;
using jint = int32_t;
using jlong = int64_t;
using jfloat = float;
using jdouble = double;

// JNI value union (for passing arguments to methods)
typedef union jvalue {
    jboolean z;
    jbyte    b;
    jchar    c;
    jshort   s;
    jint     i;
    jlong    j;
    jfloat   f;
    jdouble  d;
    jobject  l;
} jvalue;

namespace pymc {
namespace plugins {

// ===========================================================
// JNIGuard
// ===========================================================

// RAII wrapper for JNI local references
class JNIGuard {
public:
    JNIGuard(JNIEnv* env, jobject obj) : env_(env), obj_(obj) {}
    ~JNIGuard();

    jobject get() const { return obj_; }
    operator jobject() const { return obj_; }
    operator bool() const { return obj_ != nullptr; }

    // Non-copyable
    JNIGuard(const JNIGuard&) = delete;
    JNIGuard& operator=(const JNIGuard&) = delete;

    // Movable
    JNIGuard(JNIGuard&& other) noexcept : env_(other.env_), obj_(other.obj_) {
        other.obj_ = nullptr;
    }

private:
    JNIEnv* env_;
    jobject obj_;
};

// ===========================================================
// JVMClassCache
// ===========================================================

// Caches commonly used JNI class references (global refs)
class JVMClassCache {
public:
    JVMClassCache() = default;
    ~JVMClassCache() = default;

    // Register a class (converts local ref to global ref)
    void register_class(const std::string& name, JNIEnv* env, jclass local_ref);

    // Get a cached class
    jclass get_class(const std::string& name) const;

    // Check if a class is cached
    bool has_class(const std::string& name) const;

    // Release all cached classes
    void clear(JNIEnv* env);

private:
    std::unordered_map<std::string, jclass> classes_;
};

// ===========================================================
// JVMMethodCache
// ===========================================================

// Caches JNI method IDs for faster lookup
class JVMMethodCache {
public:
    using MethodKey = std::pair<std::string, std::string>;  // (class, method+sig)

    void cache_method(const std::string& class_name,
                      const std::string& method_sig,
                      jmethodID id);

    jmethodID get_method(const std::string& class_name,
                         const std::string& method_sig) const;

    bool has_method(const std::string& class_name,
                    const std::string& method_sig) const;

private:
    std::map<MethodKey, jmethodID> methods_;
};

// ===========================================================
// NativeCallback
// ===========================================================

// Represents a registered native callback (Java→C++)
struct NativeCallback {
    std::string class_name;
    std::string method_name;
    std::string method_signature;
    void* function_ptr;  // JNI native function pointer
};

// ===========================================================
// JVMBridge
// ===========================================================

class JVMBridge {
public:
    JVMBridge();
    ~JVMBridge();

    // --- JVM Lifecycle ---

    // Initialize the JVM with the given class path
    // class_path: semicolon-separated list of .jar files and directories
    // Returns: true if JVM was created successfully
    bool initialize(const std::string& class_path = "");

    // Shut down the JVM
    // Warning: This destroys the JVM and all loaded classes
    void destroy();

    // Check if JVM is initialized
    bool is_initialized() const { return jvm_ != nullptr; }

    // Get the JNIEnv for the current thread
    // Attaches the thread to the JVM if not already attached
    JNIEnv* get_env() const;

    // --- Class Loading ---

    // Load a .jar file into the JVM's class path
    // Returns: true if the jar was loaded successfully
    bool load_jar(const std::string& path);

    // Find a class by its fully qualified name
    // e.g. "org/bukkit/entity/Player"
    jclass find_class(const std::string& class_name) const;

    // --- Method Invocation ---

    // Call a static method on a class
    void call_static_void_method(const std::string& class_name,
                                  const std::string& method_name,
                                  const std::string& signature,
                                  const std::vector<jvalue>& args = {});

    jint call_static_int_method(const std::string& class_name,
                                 const std::string& method_name,
                                 const std::string& signature,
                                 const std::vector<jvalue>& args = {});

    jboolean call_static_boolean_method(const std::string& class_name,
                                         const std::string& method_name,
                                         const std::string& signature,
                                         const std::vector<jvalue>& args = {});

    jobject call_static_object_method(const std::string& class_name,
                                       const std::string& method_name,
                                       const std::string& signature,
                                       const std::vector<jvalue>& args = {});

    // Call an instance method on an object
    void call_void_method(jobject obj,
                           const std::string& class_name,
                           const std::string& method_name,
                           const std::string& signature,
                           const std::vector<jvalue>& args = {});

    jint call_int_method(jobject obj,
                          const std::string& class_name,
                          const std::string& method_name,
                          const std::string& signature,
                          const std::vector<jvalue>& args = {});

    jboolean call_boolean_method(jobject obj,
                                  const std::string& class_name,
                                  const std::string& method_name,
                                  const std::string& signature,
                                  const std::vector<jvalue>& args = {});

    jobject call_object_method(jobject obj,
                                const std::string& class_name,
                                const std::string& method_name,
                                const std::string& signature,
                                const std::vector<jvalue>& args = {});

    jdouble call_double_method(jobject obj,
                                const std::string& class_name,
                                const std::string& method_name,
                                const std::string& signature,
                                const std::vector<jvalue>& args = {});

    jfloat call_float_method(jobject obj,
                              const std::string& class_name,
                              const std::string& method_name,
                              const std::string& signature,
                              const std::vector<jvalue>& args = {});

    jlong call_long_method(jobject obj,
                            const std::string& class_name,
                            const std::string& method_name,
                            const std::string& signature,
                            const std::vector<jvalue>& args = {});

    // --- Field Access ---

    // Get a static field value
    jobject get_static_object_field(const std::string& class_name,
                                     const std::string& field_name,
                                     const std::string& signature);

    jint get_static_int_field(const std::string& class_name,
                               const std::string& field_name,
                               const std::string& signature);

    // Get an instance field value
    jobject get_object_field(jobject obj,
                              const std::string& class_name,
                              const std::string& field_name,
                              const std::string& signature);

    jint get_int_field(jobject obj,
                        const std::string& class_name,
                        const std::string& field_name,
                        const std::string& signature);

    // Set an instance field value
    void set_object_field(jobject obj,
                           const std::string& class_name,
                           const std::string& field_name,
                           const std::string& signature,
                           jobject value);

    void set_int_field(jobject obj,
                        const std::string& class_name,
                        const std::string& field_name,
                        const std::string& signature,
                        jint value);

    // --- Object Creation ---

    // Create a new object
    jobject new_object(const std::string& class_name,
                        const std::string& constructor_sig,
                        const std::vector<jvalue>& args = {});

    // Create a Java String from a C++ string
    jobject new_string(const std::string& str) const;

    // Get a C++ string from a Java String
    std::string get_string(jobject str) const;

    // --- Native Method Registration ---

    // Register a native method (C++ function callable from Java)
    bool register_native_method(const std::string& class_name,
                                 const std::string& method_name,
                                 const std::string& signature,
                                 void* function_ptr);

    // Register all native callbacks at once
    bool register_natives(const std::string& class_name,
                           const std::vector<NativeCallback>& callbacks);

    // --- Plugin-specific Operations ---

    // Call onEnable() on a JavaPlugin instance
    bool call_plugin_on_enable(jobject plugin_instance);

    // Call onDisable() on a JavaPlugin instance
    bool call_plugin_on_disable(jobject plugin_instance);

    // Call onLoad() on a JavaPlugin instance
    bool call_plugin_on_load(jobject plugin_instance);

    // --- Error Handling ---

    // Check if a Java exception is pending
    bool exception_check() const;

    // Clear a pending Java exception
    void exception_clear() const;

    // Get the description of a pending Java exception
    std::string exception_describe() const;

    // --- Utility ---

    // Get the JVM version
    std::string get_jvm_version() const;

    // Get total JVM memory usage
    jlong get_total_memory() const;

    // Get free JVM memory
    jlong get_free_memory() const;

    // Force garbage collection
    void gc();

private:
    // Internal method ID lookup (with caching)
    jmethodID get_method_id(const std::string& class_name,
                             const std::string& method_name,
                             const std::string& signature,
                             bool is_static = false) const;

    // Internal field ID lookup (with caching)
    jfieldID get_field_id(const std::string& class_name,
                           const std::string& field_name,
                           const std::string& signature,
                           bool is_static = false) const;

    // Ensure the current thread is attached to the JVM
    JNIEnv* ensure_thread_attached() const;

private:
    JavaVM* jvm_ = nullptr;
    mutable JNIEnv* env_ = nullptr;

    // Caches
    mutable JVMClassCache class_cache_;
    mutable JVMMethodCache method_cache_;

    // Loaded jar files
    std::vector<std::string> loaded_jars_;

    // Registered native callbacks
    std::vector<NativeCallback> native_callbacks_;

    // Plugin instances (class_name -> jobject global ref)
    std::unordered_map<std::string, jobject> plugin_instances_;

    // Mutex for thread safety
    mutable std::mutex mutex_;

    // Whether the bridge owns the JVM (vs attaching to existing)
    bool owns_jvm_ = false;

    // Class path components
    std::string class_path_;
};

}  // namespace plugins
}  // namespace pymc

#endif  // PYMC_JVM_BRIDGE_H
