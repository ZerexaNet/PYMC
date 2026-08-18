import json
import unittest
import zipfile
from pathlib import Path

from plugins.java_plugin import (
    BRIDGE_JAR, LIB_DIR, _jar_classpath, describe_jar, discover_jar_plugins,
)


class JavaPluginGlueTests(unittest.TestCase):
    def test_discover_jar_plugins(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nota.txt").write_text("x", encoding="utf-8")
            (root / "ExamplePlugin.jar").write_bytes(b"zip-bytes")
            discovered = discover_jar_plugins(root)
            self.assertEqual(discovered, [root / "ExamplePlugin.jar"])

    def test_describe_jar_reads_plugin_yml(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            jar = Path(tmp) / "Hello.jar"
            with zipfile.ZipFile(jar, "w") as zf:
                zf.writestr("plugin.yml",
                            "name: HelloPlugin\nmain: test.HelloPlugin\nversion: 1.2\n")
            info = describe_jar(jar)
            self.assertEqual(info["name"], "HelloPlugin")
            self.assertEqual(info["main"], "test.HelloPlugin")
            self.assertEqual(info["version"], "1.2")

    def test_bridge_artifacts_are_packaged(self):
        self.assertTrue(BRIDGE_JAR.exists())
        paper_api = list(LIB_DIR.glob("paper-api-*.jar"))
        self.assertTrue(paper_api)
        adventure_api = list(LIB_DIR.glob("adventure-api-*.jar"))
        self.assertTrue(adventure_api)
        self.assertIn(str(BRIDGE_JAR.resolve()), _jar_classpath())


if __name__ == "__main__":
    unittest.main()
