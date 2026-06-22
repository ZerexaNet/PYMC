// ============================================================
// PyMC - Mod Compatibility Layer: JVM Interface
//
// Provides a simplified JNI interface for loading and executing
// mod .jar files. This is a lighter-weight alternative to the
// full JVMBridge used for Paper/Bukkit plugins, optimized for
// the specific needs of Fabric/Forge/NeoForge/Quilt mods.
//
// Architecture:
//   JVMInterface
//     ├── JVM Initialization
//     │   ├── Locate JVM library (jvm.so / jvm.dll)
//     │   ├── Create JVM with mod-specific class path
//     │   └── Configure JVM options (memory, GC, etc.)
//     ├── Mod Jar Loading
//     │   ├── Add jar to class path
//     │   ├── Find mod entry point class
//     │   ├── Call mod initializer method
//     │   └── Track loaded mod classes
//     ├── Method Invocation
//     │   ├── Static method calls
//     │   ├── Instance method calls
//     │   └── Constructor invocation
//     ├── Field Access
//     │   ├── Static field read/write
//     │   └── Instance field read/write
//     ├── Native Callback Registration
//     │   ├── Register C++ functions callable from Java
//     │   ├── Auto-generate JNI method signatures
//     │   └── Marshal arguments between Java and C++
//     └── Thread Management
//         ├── Attach/detach native threads to JVM
//         └── Thread-safe access to JNI environment
//
// Difference from JVMBridge (plugins/jvm_bridge.h):
//   - JVMInterface is simpler and focused on mod loading
//   - JVMBridge provides full Bukkit/Paper API compatibility
//   - JVMInterface handles Fabric/Forge/NeoForge/Quilt specifics
//   - Both can coexist; JVMInterface uses the same JVM instance
//     if one is already running
//
// JVM discovery:
//   1. Check JAVA_HOME environment variable
//   2. Check common install paths (/usr/lib/jvm, Program Files)
//   3. Try "java" on PATH and derive JVM location
//   4. Fall back to user-specified path
// ============================================================

#ifndef PYMC_JVM_INTERFACE_H
#define PYMC_JVM_INTERFACE_H

#include <string>
#include <vector>
#include <map>
#include <unordered_map>
#include <functional>
#include <memory>
#include <mutex>
#include <cstdint>
#include <optional>

namespace pymc {
namespace mods {

// ===========================================================
// JVM Configuration
// ===========================================================

struct JVMConfig {
    // JVM library path (empty = auto-detect)
    std::string jvm_path;

    // Class path entries (jar files and directories)
    std::vector<std::string> class_path;

    // JVM heap size
    int min_heap_mb = 256;               // -Xms
    int max_heap_mb = 1024;              // -Xmx

    // Additional JVM options
    std::vector<std::string> jvm_options;

    // Whether to use the JVM's class loader for mod jars
    // (vs. custom URLClassLoader)
    bool use_system_classloader = false;

    // Native library paths
    std::vector<std::string> native_library_paths;

    // Whether to attach the current thread on initialize
    bool attach_current_thread = true;
};

// ===========================================================
// JVMClassInfo
// ===========================================================

// Cached information about a loaded Java class
struct JVMClassInfo {
    std::string class_name;              // Fully qualified class name (with / separators)
    std::string simple_name;             // Simple class name
    std::vector<std::string> methods;    // Known method names
    std::vector<std::string> fields;     // Known field names
    bool is_interface = false;
    bool is_abstract = false;
    std::string super_class;             // Super class name
    std::vector<std::string> interfaces; // Implemented interfaces
};

// ===========================================================
// NativeCallbackInfo
// ===========================================================

// Information about a registered native callback
struct NativeCallbackInfo {
    std::string class_name;              // Java class that declares the native method
    std::string method_name;             // Native method name
    std::string method_signature;        // JNI method signature
    std::function<std::string(const std::vector<std::string>&)> callback;  // C++ callback

    // The registered JNI function pointer (set during registration)
    void* registered_function_ptr = nullptr;
};

// ===========================================================
// JVMInterface
// ===========================================================

class JVMInterface {
public:
    JVMInterface();
    ~JVMInterface();

    // --- JVM Lifecycle ---

    // Initialize the JVM with the given configuration
    // If jvm_path is empty, auto-detects JVM location
    // Returns: true if JVM was created/attached successfully
    bool initialize(const std::string& jvm_path = "");

    // Initialize with full configuration
    bool initialize(const JVMConfig& config);

    // Shut down the JVM
    // Warning: This destroys the JVM and all loaded classes
    // Only call this if you own the JVM (i.e., you created it)
    void shutdown();

    // Check if JVM is initialized
    bool is_initialized() const { return jvm_ != nullptr; }

    // Check if this interface owns the JVM (vs. attaching to existing)
    bool owns_jvm() const { return owns_jvm_; }

    // --- Mod Jar Loading ---

    // Load a .jar file and call its entry point
    // For Fabric: calls the ModInitializer.onInitialize() method
    // For Forge: calls the @Mod constructor
    // For NeoForge: calls the @Mod constructor
    // For Quilt: calls the ModInitializer.onInitialize() method
    bool load_and_init_mod(const std::string& jar_path, const std::string& main_class);

    // Add a jar to the class path without initializing
    bool add_to_classpath(const std::string& jar_path);

    // Find a class in a loaded jar
    std::optional<std::string> find_class_in_jar(const std::string& jar_path,
                                                   const std::string& class_name);

    // --- Method Invocation ---

    // Call a static method on a loaded class
    // Args are passed as strings and converted to appropriate Java types
    // based on the method signature
    std::string call_static_method(const std::string& class_name,
                                   const std::string& method_name,
                                   const std::vector<std::string>& args);

    // Call a static method with no arguments
    std::string call_static_method(const std::string& class_name,
                                   const std::string& method_name);

    // Call an instance method on an object
    // object_handle is a string representation of the object reference
    std::string call_instance_method(const std::string& object_handle,
                                     const std::string& class_name,
                                     const std::string& method_name,
                                     const std::vector<std::string>& args);

    // Call a constructor and return the object handle
    std::string call_constructor(const std::string& class_name,
                                 const std::vector<std::string>& args);

    // --- Native Callback Registration ---

    // Register a native callback that Java code can call
    // When Java code calls the native method, the C++ callback is invoked
    void register_native_callback(const std::string& class_name,
                                  const std::string& method_name,
                                  std::function<std::string(const std::vector<std::string>&)> callback);

    // Register a native callback with explicit JNI signature
    void register_native_callback(const std::string& class_name,
                                  const std::string& method_name,
                                  const std::string& method_signature,
                                  std::function<std::string(const std::vector<std::string>&)> callback);

    // Commit all registered native callbacks (must be called before
    // the Java class that uses them is loaded)
    bool commit_native_callbacks();

    // --- Field Access ---

    // Get a field value from a loaded class (static field)
    std::string get_field(const std::string& class_name, const std::string& field_name);

    // Set a static field value
    bool set_field(const std::string& class_name, const std::string& field_name,
                   const std::string& value);

    // Get an instance field value
    std::string get_instance_field(const std::string& object_handle,
                                    const std::string& class_name,
                                    const std::string& field_name);

    // Set an instance field value
    bool set_instance_field(const std::string& object_handle,
                            const std::string& class_name,
                            const std::string& field_name,
                            const std::string& value);

    // --- Thread Management ---

    // Attach the current thread to the JVM
    // Required before making JNI calls from a non-JVM thread
    bool attach_current_thread();

    // Detach the current thread from the JVM
    void detach_current_thread();

    // Check if the current thread is attached to the JVM
    bool is_current_thread_attached() const;

    // --- Class Information ---

    // Get information about a loaded class
    std::optional<JVMClassInfo> get_class_info(const std::string& class_name);

    // List all loaded classes (for debugging)
    std::vector<std::string> list_loaded_classes() const;

    // --- Error Handling ---

    // Check if a Java exception is pending
    bool has_exception() const;

    // Get the exception message (and clear the exception)
    std::string get_and_clear_exception();

    // --- Utility ---

    // Get the JVM version string
    std::string get_jvm_version() const;

    // Get the JVM's total memory in bytes
    int64_t get_total_memory() const;

    // Get the JVM's free memory in bytes
    int64_t get_free_memory() const;

    // Get loaded jar paths
    const std::vector<std::string>& get_loaded_jars() const { return loaded_jars_; }

    // Auto-detect JVM path
    // Searches common locations for a JDK/JRE installation
    static std::string detect_jvm_path();

private:
    // Internal: get or create JNIEnv for the current thread
    void* get_env() const;

    // Internal: find a class by name (with caching)
    void* find_class_internal(const std::string& class_name) const;

    // Internal: get method ID (with caching)
    void* get_method_id_internal(const std::string& class_name,
                                  const std::string& method_name,
                                  const std::string& signature,
                                  bool is_static) const;

    // Internal: get field ID (with caching)
    void* get_field_id_internal(const std::string& class_name,
                                 const std::string& field_name,
                                 const std::string& signature,
                                 bool is_static) const;

    // Internal: create the JVM
    bool create_jvm(const JVMConfig& config);

    // Internal: attach to an existing JVM
    bool attach_to_existing_jvm();

private:
    // JVM pointers (void* to avoid requiring jni.h in this header)
    void* jvm_ = nullptr;           // JavaVM*
    void* env_ = nullptr;           // JNIEnv* (for the main thread)

    // Whether this interface owns the JVM
    bool owns_jvm_ = false;

    // Configuration used to initialize the JVM
    JVMConfig config_;

    // Loaded jar files
    std::vector<std::string> loaded_jars_;

    // Registered native callbacks (pending commit)
    std::vector<NativeCallbackInfo> pending_callbacks_;

    // Committed native callbacks
    std::vector<NativeCallbackInfo> committed_callbacks_;

    // Loaded class cache (class_name -> class info)
    mutable std::unordered_map<std::string, JVMClassInfo> class_cache_;

    // Method ID cache (class_name::method_name::signature -> methodID)
    mutable std::unordered_map<std::string, void*> method_cache_;

    // Field ID cache (class_name::field_name::signature -> fieldID)
    mutable std::unordered_map<std::string, void*> field_cache_;

    // Object handles (handle_string -> jobject global ref)
    // Used for instance method calls
    std::unordered_map<std::string, void*> object_handles_;

    // Mutex for thread safety
    mutable std::mutex mutex_;
};

}  // namespace mods
}  // namespace pymc

#endif  // PYMC_JVM_INTERFACE_H
