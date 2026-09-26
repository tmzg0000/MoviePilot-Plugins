def task_info(label: str = None, hint: str = None):
    def decorator(func):
        func._task_meta = {
            "label_template": label or func.__name__,
            "hint_template": hint or f"执行 {func.__name__} 任务"
        }
        return func
    return decorator
