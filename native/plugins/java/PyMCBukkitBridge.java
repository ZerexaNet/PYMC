import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import org.bukkit.Bukkit;
import org.bukkit.Server;
import org.bukkit.command.Command;
import org.bukkit.command.CommandMap;
import org.bukkit.command.CommandSender;
import org.bukkit.command.ConsoleCommandSender;
import org.bukkit.command.PluginCommand;
import org.bukkit.event.Event;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.plugin.EventExecutor;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.PluginDescriptionFile;
import org.bukkit.plugin.PluginLoader;
import org.bukkit.plugin.PluginManager;
import org.bukkit.plugin.RegisteredListener;
import io.papermc.paper.ServerBuildInfo;
import net.kyori.adventure.key.Key;
import org.bukkit.UnsafeValues;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.OptionalInt;
import java.util.Set;
import java.util.logging.Logger;
import java.util.regex.Pattern;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;

public final class PyMCBukkitBridge {
    public static void main(String[] args) throws Exception {
        File pluginDir = args.length > 0 ? new File(args[0]) : new File("plugins");
        Bridge bridge = new Bridge(pluginDir);
        bridge.run();
    }

    static final class Bridge {
        private static final Gson GSON = new Gson();
        private static final Logger LOG = Logger.getLogger("PyMC-BukkitBridge");

        private final File pluginDir;
        private final Server server;
        private final PluginManager pluginManager;
        private final CommandMap commandMap;
        private final CommandSender console;
        private final UnsafeValues unsafeValues;
        private final Map<String, Command> commands = new LinkedHashMap<>();

        private final Map<String, Plugin> plugins = new LinkedHashMap<>();
        private final Map<String, JsonObject> pluginDescriptions = new LinkedHashMap<>();
        private final Map<Class<? extends Event>, List<RegisteredListener>> listeners = new LinkedHashMap<>();

        Bridge(File pluginDir) throws Exception {
            this.pluginDir = pluginDir;
            this.commandMap = proxy(CommandMap.class, new InvocationHandler() {
                public Object invoke(Object proxy, Method m, Object[] a) {
                    String n = m.getName();
                    switch (n) {
                        case "register": {
                            Command cmd = a.length == 2 ? (Command) a[1] : (Command) a[2];
                            commands.put(cmd.getName().toLowerCase(Locale.ROOT), cmd);
                            return true;
                        }
                        case "registerAll": {
                            @SuppressWarnings("unchecked")
                            List<Command> list = (List<Command>) a[a.length - 1];
                            for (Command cmd : list) commands.put(cmd.getName().toLowerCase(Locale.ROOT), cmd);
                            return null;
                        }
                        case "getCommand": return commands.get(((String) a[0]).toLowerCase(Locale.ROOT));
                        case "getCommands": return new ArrayList<>(commands.values());
                        case "getKnownCommands": return new HashMap<>(commands);
                        case "dispatch": return dispatchCommand((CommandSender) a[0], (String) a[1]);
                        case "tabComplete": {
                            CommandSender sender = (CommandSender) a[0];
                            String line = (String) a[a.length - 1];
                            return tabComplete(sender, line);
                        }
                        default: return defaultFor(m.getReturnType());
                    }
                }
            });
            this.unsafeValues = proxy(UnsafeValues.class, (proxyObj, m, a) -> defaultFor(m.getReturnType()));
            this.console = proxy(ConsoleCommandSender.class, new InvocationHandler() {
                public Object invoke(Object proxy, Method m, Object[] a) {
                    String n = m.getName();
                    if (n.equals("getName") || n.equals("name")) return "CONSOLE";
                    if (n.equals("sendMessage") || n.equals("sendPlainMessage")) {
                        if (a != null && a.length > 0 && a[0] != null) emit("console", String.valueOf(a[0]));
                        return null;
                    }
                    if (n.equals("getServer")) return server;
                    return defaultFor(m.getReturnType());
                }
            });

            this.pluginManager = proxy(PluginManager.class, new InvocationHandler() {
                public Object invoke(Object proxy, Method m, Object[] a) {
                    String n = m.getName();
                    switch (n) {
                        case "getPlugin": {
                            String name = (String) a[0];
                            Plugin p = plugins.get(name.toLowerCase(Locale.ROOT));
                            if (p == null) {
                                for (Plugin pp : plugins.values()) {
                                    if (pp.getName().equalsIgnoreCase(name)) return pp;
                                }
                            }
                            return p;
                        }
                        case "getPlugins": return plugins.values().toArray(new Plugin[0]);
                        case "isPluginEnabled": {
                            if (a[0] instanceof String) {
                                Plugin p = plugins.get(((String) a[0]).toLowerCase(Locale.ROOT));
                                return p != null && p.isEnabled();
                            }
                            return ((Plugin) a[0]).isEnabled();
                        }
                        case "registerEvents": return registerEvents((Listener) a[0], (Plugin) a[1]);
                        case "callEvent": return callEvent((Event) a[0]);
                        case "enablePlugin": enablePlugin((Plugin) a[0]); return null;
                        case "disablePlugin": disablePlugin((Plugin) a[0]); return null;
                        default: return defaultFor(m.getReturnType());
                    }
                }
            });

            this.server = proxy(Server.class, new InvocationHandler() {
                public Object invoke(Object proxy, Method m, Object[] a) {
                    String n = m.getName();
                    switch (n) {
                        case "getName": return "PyMC";
                        case "getVersion": return "1.21.1";
                        case "getBukkitVersion": return "1.21.1-PyMC";
                        case "getMinecraftVersion": return "1.21.1";
                        case "getPluginManager": return pluginManager;
                        case "getCommandMap": return commandMap;
                        case "getLogger": return LOG;
                        case "getUnsafe": return unsafeValues;
                        case "getConsoleSender": return console;
                        case "broadcastMessage": {
                            if (a != null && a.length > 0 && a[0] != null) {
                                emit("broadcast", String.valueOf(a[0]));
                                return 1;
                            }
                            return 0;
                        }
                        case "getOnlinePlayers": return Collections.emptyList();
                        case "getPlayer": return null;
                        case "getWorlds": return Collections.emptyList();
                        case "getWorld": return null;
                        case "getPluginCommand": {
                            Command c = commandMap.getCommand((String) a[0]);
                            return (c instanceof PluginCommand) ? c : null;
                        }
                        case "dispatchCommand": return dispatchCommand((CommandSender) a[0], (String) a[1]);
                        case "createCommandSender": return console;
                        default: return defaultFor(m.getReturnType());
                    }
                }
            });
            try {
                java.lang.reflect.Field f = Bukkit.class.getDeclaredField("server");
                f.setAccessible(true);
                f.set(null, this.server);
            } catch (Throwable t) {
                throw new IllegalStateException("cannot bind Bukkit.server", t);
            }
        }

        void run() {
            BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
            emit("ready", null);
            String line;
            try {
                while ((line = in.readLine()) != null) {
                    line = line.trim();
                    if (line.isEmpty()) continue;
                    try {
                        handle(GSON.fromJson(line, JsonObject.class));
                    } catch (Throwable t) {
                        t.printStackTrace();
                        emit("error", t.toString());
                    }
                }
            } catch (Exception e) {
                emit("error", e.toString());
            } finally {
                for (Plugin p : new ArrayList<>(plugins.values())) disablePlugin(p);
            }
        }

        private void handle(JsonObject o) throws Exception {
            String cmd = str(o, "cmd");
            if (cmd == null) return;
            switch (cmd) {
                case "load_all": {
                    File[] jars = pluginDir.listFiles(f -> f.getName().toLowerCase(Locale.ROOT).endsWith(".jar"));
                    JsonArray arr = new JsonArray();
                    if (jars != null) {
                        Arrays.sort(jars, Comparator.comparing(File::getName));
                        for (File jar : jars) {
                            JsonObject r = new JsonObject();
                            try {
                                loadPluginJar(jar, r);
                            } catch (Throwable t) {
                                t.printStackTrace();
                                r.addProperty("status", "error");
                                r.addProperty("error", exceptionString(t));
                            }
                            arr.add(r);
                        }
                    }
                    JsonObject out = new JsonObject();
                    out.add("plugins", arr);
                    emit("loaded", out);
                    break;
                }
                case "load": loadPluginJar(new File(str(o, "jar")), null); break;
                case "enable_all": for (String name : new ArrayList<>(plugins.keySet())) enablePlugin(plugins.get(name)); break;
                case "disable_all": for (Plugin p : new ArrayList<>(plugins.values())) disablePlugin(p); break;
                case "enable": enablePluginByName(str(o, "name")); break;
                case "disable": disablePluginByName(str(o, "name")); break;
                case "dispatch": {
                    String l = str(o, "line");
                    if (l != null) {
                        boolean ok = dispatchCommand(console, l.trim());
                        JsonObject out = new JsonObject();
                        out.addProperty("ok", ok);
                        emit("dispatched", out);
                    }
                    break;
                }
                case "broadcast": {
                    String msg = str(o, "message");
                    if (msg != null) emit("broadcast", msg);
                    break;
                }
                case "status": {
                    JsonArray arr = new JsonArray();
                    for (Plugin p : plugins.values()) arr.add(p.getName());
                    JsonObject out = new JsonObject();
                    out.addProperty("count", plugins.size());
                    out.add("plugins", arr);
                    emit("status", out);
                    break;
                }
                case "shutdown": return;
            }
        }

        private void loadPluginJar(File jarFile, JsonObject result) throws Exception {
            JsonObject desc = readPluginDescription(jarFile);
            String name = str(desc, "name");
            String main = str(desc, "main");
            String version = str(desc, "version");
            if (name == null || main == null) throw new IllegalStateException(jarFile.getName() + " lacks plugin.yml name/main");

            PluginDescriptionFile pdf = new PluginDescriptionFile(name, version == null ? "0.0.0" : version, main);
            URLClassLoader loader = new URLClassLoader(new URL[]{jarFile.toURI().toURL()},
                    PyMCBukkitBridge.class.getClassLoader());
            Class<?> mainClass = Class.forName(main, true, loader);
            if (!JavaPlugin.class.isAssignableFrom(mainClass)) {
                throw new IllegalStateException(main + " does not extend JavaPlugin");
            }

            JavaPlugin plugin = (JavaPlugin) allocateWithoutConstructor(mainClass);
            File dataFolder = new File(pluginDir, name);
            dataFolder.mkdirs();
            PyMCPluginLoader pl = new PyMCPluginLoader(server, pdf, this);
            initializePlugin(plugin, pl, pdf, dataFolder, jarFile, loader, name);

            String key = name.toLowerCase(Locale.ROOT);
            plugins.put(key, plugin);
            pluginDescriptions.put(key, desc);
            plugin.onLoad();
            plugin.setEnabled(true);
            plugin.onEnable();
            registerPluginCommands(plugin, desc);

            JsonObject out = result != null ? result : new JsonObject();
            out.addProperty("status", "enabled");
            out.addProperty("name", name);
            out.addProperty("main", main);
            if (result == null) {
                JsonObject wrapper = new JsonObject();
                wrapper.add("plugin", out);
                emit("loaded", wrapper);
            } else {
                emit("loaded", out);
            }
        }

        private void initializePlugin(JavaPlugin plugin, PluginLoader loader, PluginDescriptionFile pdf,
                                      File dataFolder, File file, ClassLoader classLoader, String name) throws Exception {
            setField(plugin, "loader", loader);
            setField(plugin, "server", server);
            setField(plugin, "file", file);
            setField(plugin, "description", pdf);
            setField(plugin, "pluginMeta", pdf);
            setField(plugin, "dataFolder", dataFolder);
            setField(plugin, "classLoader", classLoader);
            setField(plugin, "logger", Logger.getLogger("PyMC." + name));
        }

        private static void setField(Object target, String name, Object value) throws Exception {
            Class<?> c = target.getClass();
            while (c != null && c != Object.class) {
                Field[] fields = c.getDeclaredFields();
                for (Field f : fields) {
                    if (f.getName().equals(name)) {
                        f.setAccessible(true);
                        f.set(target, value);
                        return;
                    }
                }
                c = c.getSuperclass();
            }
            throw new NoSuchFieldException(name);
        }

        @SuppressWarnings("unchecked")
        private void registerPluginCommands(JavaPlugin plugin, JsonObject desc) {
            JsonObject cmds = desc.getAsJsonObject("commands");
            if (cmds == null) return;
            for (Map.Entry<String, JsonElement> e : cmds.entrySet()) {
                String name = e.getKey();
                try {
                    Constructor<PluginCommand> c = PluginCommand.class.getDeclaredConstructor(String.class, Plugin.class);
                    c.setAccessible(true);
                    PluginCommand pc = c.newInstance(name, plugin);
                    pc.setExecutor((sender, command, label, args) -> plugin.onCommand(sender, command, label, args));
                    if (e.getValue().isJsonObject() && e.getValue().getAsJsonObject().has("description")) {
                        pc.setDescription(e.getValue().getAsJsonObject().get("description").getAsString());
                    }
                    commandMap.register(plugin.getName(), pc);
                } catch (Throwable t) {
                    LOG.warning("Failed to register command /" + name + ": " + t);
                }
            }
        }

        private void enablePluginByName(String name) {
            Plugin p = plugins.get(name.toLowerCase(Locale.ROOT));
            if (p != null) enablePlugin(p);
        }
        private void disablePluginByName(String name) {
            Plugin p = plugins.get(name.toLowerCase(Locale.ROOT));
            if (p != null) disablePlugin(p);
        }
        private void enablePlugin(Plugin p) {
            JavaPlugin jp = (JavaPlugin) p;
            if (!jp.isEnabled()) {
                jp.setEnabled(true);
                jp.onEnable();
            }
            JsonObject o = new JsonObject();
            o.addProperty("name", jp.getName());
            o.addProperty("enabled", jp.isEnabled());
            emit("plugin_enabled", o);
        }
        private void disablePlugin(Plugin p) {
            JavaPlugin jp = (JavaPlugin) p;
            if (jp.isEnabled()) {
                jp.onDisable();
                jp.setEnabled(false);
            }
            JsonObject o = new JsonObject();
            o.addProperty("name", jp.getName());
            o.addProperty("enabled", false);
            emit("plugin_disabled", o);
        }

        private boolean dispatchCommand(CommandSender sender, String line) {
            if (line.startsWith("/")) line = line.substring(1);
            String[] parts = line.trim().split("\s+", 2);
            if (parts.length == 0 || parts[0].isEmpty()) return false;
            String label = parts[0];
            String[] args = parts.length > 1 && !parts[1].isEmpty()
                    ? parts[1].split("\s+") : new String[0];
            Command cmd = commands.get(label.toLowerCase(Locale.ROOT));
            if (cmd == null) return false;
            try {
                return cmd.execute(sender, label, args);
            } catch (Throwable t) {
                LOG.warning("dispatch failed: " + t);
                return false;
            }
        }

        private List<String> tabComplete(CommandSender sender, String line) {
            if (line.startsWith("/")) line = line.substring(1);
            String[] parts = line.trim().split("\s+", -1);
            if (parts.length == 0) return Collections.emptyList();
            Command cmd = commands.get(parts[0].toLowerCase(Locale.ROOT));
            if (cmd == null) return Collections.emptyList();
            String[] args = parts.length > 1
                    ? Arrays.copyOfRange(parts, 1, parts.length) : new String[0];
            try {
                return cmd.tabComplete(sender, parts[0], args);
            } catch (Throwable t) {
                return Collections.emptyList();
            }
        }

        private int registerEvents(Listener listener, Plugin plugin) {
            PyMCPluginLoader pl = new PyMCPluginLoader(server, plugin.getDescription(), this);
            try {
                Map<Class<? extends Event>, Set<RegisteredListener>> parsed = pl.createRegisteredListeners(listener, plugin);
                for (Map.Entry<Class<? extends Event>, Set<RegisteredListener>> e : parsed.entrySet()) {
                    listeners.computeIfAbsent(e.getKey(), k -> new ArrayList<>()).addAll(e.getValue());
                }
                return parsed.size();
            } catch (Throwable t) {
                LOG.warning("registerEvents failed: " + t);
                return 0;
            }
        }

        private boolean callEvent(Event event) {
            List<RegisteredListener> list = listeners.get(event.getClass());
            if (list == null) return false;
            for (RegisteredListener rl : new ArrayList<>(list)) {
                try {
                    rl.callEvent(event);
                } catch (Throwable t) {
                    LOG.warning("event listener failed: " + t);
                }
            }
            return true;
        }

        private static JsonObject readPluginDescription(File jarFile) throws Exception {
            try (JarFile jar = new JarFile(jarFile)) {
                JarEntry entry = jar.getJarEntry("plugin.yml");
                if (entry == null) throw new IllegalStateException("plugin.yml missing");
                String yaml = new String(jar.getInputStream(entry).readAllBytes(), StandardCharsets.UTF_8);
                return parsePluginYml(yaml);
            }
        }

        private static JsonObject parsePluginYml(String yaml) {
            JsonObject o = new JsonObject();
            JsonObject commands = new JsonObject();
            boolean inCommands = false;
            for (String line : yaml.split("\\R")) {
                String t = line.trim();
                if (t.isEmpty() || t.startsWith("#")) continue;
                if (!line.startsWith(" ") && !line.startsWith("\t")) {
                    inCommands = t.startsWith("commands:");
                    int colon = t.indexOf(':');
                    if (colon > 0) {
                        String key = t.substring(0, colon).trim();
                        String value = t.substring(colon + 1).trim().replaceAll("^['\"]|['\"]$", "");
                        if (!key.equals("commands")) o.addProperty(key, value);
                    }
                } else if (inCommands) {
                    int colon = t.indexOf(':');
                    if (colon > 0 && !t.startsWith("-")) {
                        String cmd = t.substring(0, colon).trim();
                        commands.add(cmd, new JsonObject());
                    }
                }
            }
            if (commands.size() > 0) o.add("commands", commands);
            return o;
        }

        private void emit(String event, Object data) {
            JsonObject o = new JsonObject();
            o.addProperty("event", event);
            if (data != null) o.add("data", GSON.toJsonTree(data));
            System.out.println(GSON.toJson(o));
            System.out.flush();
        }

        private static String str(JsonObject o, String key) {
            JsonElement e = o.get(key);
            return e == null ? null : e.getAsString();
        }

        private static String exceptionString(Throwable t) {
            StringBuilder sb = new StringBuilder(t.toString());
            for (Throwable c = t.getCause(); c != null && sb.length() < 3000; c = c.getCause()) {
                sb.append(" <- ").append(c.toString());
            }
            return sb.toString();
        }

        private static Object defaultFor(Class<?> type) {
            if (type == boolean.class) return false;
            if (type == int.class) return 0;
            if (type == long.class) return 0L;
            if (type == double.class) return 0.0;
            if (type == float.class) return 0.0f;
            if (type == short.class) return (short) 0;
            if (type == byte.class) return (byte) 0;
            if (type == char.class) return 
(char) 0;
            if (type == String.class) return "";
            if (type == List.class || type == Collection.class || type == Set.class) return Collections.emptyList();
            if (type == Map.class) return Collections.emptyMap();
            return null;
        }

        @SuppressWarnings("unchecked")
        private static <T> T proxy(Class<T> iface, InvocationHandler handler) {
            ClassLoader cl = iface.getClassLoader();
            return iface.cast(Proxy.newProxyInstance(
                    cl != null ? cl : PyMCBukkitBridge.class.getClassLoader(),
                    new Class<?>[]{iface}, handler));
        }
    }

    @SuppressWarnings("unchecked")
    private static <T> T allocateWithoutConstructor(Class<T> type) throws Exception {
        try {
            Class<?> unsafeClass = Class.forName("sun.misc.Unsafe");
            java.lang.reflect.Field f = unsafeClass.getDeclaredField("theUnsafe");
            f.setAccessible(true);
            Object unsafe = f.get(null);
            Method allocate = unsafeClass.getMethod("allocateInstance", Class.class);
            return (T) allocate.invoke(unsafe, type);
        } catch (Exception e) {
            throw new IllegalStateException("cannot allocate " + type.getName(), e);
        }
    }

    public static final class BuildInfo implements ServerBuildInfo {
        public Key brandId() { return Key.key("pymc", "paper"); }
        public boolean isBrandCompatible(Key key) { return true; }
        public String brandName() { return "PyMC"; }
        public String minecraftVersionId() { return "1.21.1"; }
        public String minecraftVersionName() { return "1.21.1"; }
        public OptionalInt buildNumber() { return OptionalInt.of(1); }
        public Instant buildTime() { return Instant.now(); }
        public java.util.Optional<String> gitBranch() { return java.util.Optional.empty(); }
        public java.util.Optional<String> gitCommit() { return java.util.Optional.empty(); }
        public String asString(ServerBuildInfo.StringRepresentation representation) { return "PyMC-1.21.1"; }
    }

    static final class PyMCPluginLoader implements PluginLoader {
        private final Server server;
        private final PluginDescriptionFile description;
        private final Bridge bridge;

        PyMCPluginLoader(Server server, PluginDescriptionFile description, Bridge bridge) {
            this.server = server;
            this.description = description;
            this.bridge = bridge;
        }

        public Plugin loadPlugin(File file) {
            throw new UnsupportedOperationException();
        }

        public PluginDescriptionFile getPluginDescription(File file) {
            return description;
        }

        public Pattern[] getPluginFileFilters() {
            return new Pattern[]{Pattern.compile("\\.jar$")};
        }

        public Map<Class<? extends Event>, Set<RegisteredListener>> createRegisteredListeners(Listener listener, Plugin plugin) {
            Map<Class<? extends Event>, Set<RegisteredListener>> map = new HashMap<>();
            for (Method m : listener.getClass().getDeclaredMethods()) {
                EventHandler ann = m.getAnnotation(EventHandler.class);
                if (ann == null || m.getParameterCount() != 1) continue;
                Class<?> pt = m.getParameterTypes()[0];
                if (!Event.class.isAssignableFrom(pt)) continue;
                @SuppressWarnings("unchecked")
                Class<? extends Event> ec = (Class<? extends Event>) pt;
                EventPriority prio = ann.priority();
                EventExecutor executor = (listenerObj, event) -> {
                    try {
                        m.setAccessible(true);
                        m.invoke(listenerObj, event);
                    } catch (Throwable t) {
                        Bridge.LOG.warning("listener invocation failed: " + t);
                    }
                };
                RegisteredListener rl = new RegisteredListener(listener, executor, prio, plugin, ann.ignoreCancelled());
                map.computeIfAbsent(ec, k -> new LinkedHashSet<>()).add(rl);
            }
            return map;
        }

        public void enablePlugin(Plugin plugin) {
            if (plugin instanceof JavaPlugin) ((JavaPlugin) plugin).setEnabled(true);
        }

        public void disablePlugin(Plugin plugin) {
            if (plugin instanceof JavaPlugin) ((JavaPlugin) plugin).setEnabled(false);
        }
    }
}
