from contextvars import ContextVar
try:
    class MyVar(ContextVar):
        def __call__(self, val):
            return self.set(val)

    cv = MyVar("test", default=0)
    print(f"Initial: {cv.get()}")
    token = cv(1)
    print(f"After call: {cv.get()}")
    cv.reset(token)
    print(f"After reset: {cv.get()}")
except TypeError as e:
    print(f"Subclassing ContextVar failed: {e}")
except Exception as e:
    print(f"An error occurred: {e}")
