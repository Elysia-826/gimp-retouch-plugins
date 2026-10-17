import contextlib


@contextlib.contextmanager
def undo_group(image):
    started = image.undo_group_start()
    try:
        yield
    finally:
        if started:
            image.undo_group_end()
