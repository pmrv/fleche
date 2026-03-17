with open('src/fleche/storage/sql.py', 'r') as f:
    content = f.read()

# To make the dataclass pickleable, we need to implement __getstate__ and __setstate__
# because `engine` and `session` (sessionmaker) are not easily pickleable.
# We can exclude them from the state, and `__post_init__` handles their creation anyway, but `__setstate__` needs to call `__post_init__` or manually recreate them.
import re
new_methods = """
    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("engine", None)
        state.pop("session", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        # Re-initialize unpickleable fields
        self.engine = create_engine(self.url, echo=self.echo, future=True)
        _enable_sqlite_foreign_keys(self.engine)
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )
"""

content = content.replace("    def _save(self, call: Call) -> Digest:", new_methods + "\n    def _save(self, call: Call) -> Digest:")

with open('src/fleche/storage/sql.py', 'w') as f:
    f.write(content)
