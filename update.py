import re

with open("src/fleche/storage/bagofholding_file.py", "r") as f:
    content = f.read()

content = content.replace("from typing import Any", "from typing import Any\nimport logging\n\nlogger = logging.getLogger(\"fleche.storage.bagofholding_file\")")

new_load = """    def _load(self, key: str) -> Any:
        try:
            return H5Bag(self._path(key)).load()
        except FileNotFoundError:
            raise KeyError(key) from None
        except OSError as e:
            logger.error(f"Corrupt file present in cache for key {key}: {e}")
            raise KeyError(key) from e"""

content = re.sub(r'    def _load\(self, key: str\) -> Any:.*', new_load, content, flags=re.DOTALL)

with open("src/fleche/storage/bagofholding_file.py", "w") as f:
    f.write(content)
