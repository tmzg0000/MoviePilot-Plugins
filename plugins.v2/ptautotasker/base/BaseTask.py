import inspect
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import functools
import traceback

@dataclass
class TaskResult:
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error: Optional[str] = None
    raw: Any = None


class BaseTask:
    def __init__(self, client):
        self.client = client

    def _find_task_meta(self, name):
        """在类的 MRO 中查找首个定义了 _task_meta 的同名函数并返回其 meta"""
        for base in self.__class__.__mro__:
            func = base.__dict__.get(name)
            if func and hasattr(func, "_task_meta"):
                return getattr(func, "_task_meta")
        return None

    def _normalize_task_result(self, raw: Any) -> TaskResult:
        """将各种可能的返回值标准化为 TaskResult"""
        if isinstance(raw, TaskResult):
            return raw

        # 如果已经是 dict，允许包含 success/data/message/error 等
        if isinstance(raw, dict):
            success = bool(raw.get("success", raw.get("ok", True)))
            data = raw.get("data", {k: v for k, v in raw.items() if k not in ("success", "ok", "message", "error")})
            message = str(raw.get("message", ""))
            error = raw.get("error")
            return TaskResult(success=success, data=data, message=message, error=error, raw=raw)

        # 布尔直接表示是否成功
        if isinstance(raw, bool):
            return TaskResult(success=raw, raw=raw)

        # 二元元组或列表 (success, data_or_message)
        if isinstance(raw, (list, tuple)) and len(raw) == 2 and isinstance(raw[0], bool):
            success = raw[0]
            second = raw[1]
            if isinstance(second, dict):
                return TaskResult(success=success, data=second, raw=raw)
            return TaskResult(success=success, message=str(second), raw=raw)

        # 异常对象：标记为失败并保存堆栈
        if isinstance(raw, BaseException):
            return TaskResult(success=False, message=str(raw), error="".join(traceback.format_exception_only(type(raw), raw)), raw=raw)

        # 其他任意返回：视为成功（保留原始返回），如果为 None 则视为失败
        if raw is None:
            return TaskResult(success=False, message="no result", raw=raw)
        return TaskResult(success=True, data={"result": raw}, raw=raw)

    def _task_wrapper_for(self, bound_method):
        """返回一个包装器，使被调用时强制返回 TaskResult"""
        @functools.wraps(bound_method)
        def wrapper(*args, **kwargs) -> TaskResult:
            try:
                raw = bound_method(*args, **kwargs)
            except Exception as e:
                # 捕获异常并返回失败的 TaskResult（方便上层记录和重试）
                return self._normalize_task_result(e)
            return self._normalize_task_result(raw)
        return wrapper


    def get_registered_tasks(self):
        """收集当前实例所有注册的任务：仅包含子类实际定义/重写的方法（若子类未定义则忽略父类的方法）。
        若子类重写了方法但未重新装饰，会回退到父类查找 _task_meta。
        """
        tasks = []
        for name, method in inspect.getmembers(self.__class__, predicate=inspect.isfunction):
            # 仅处理在子类中实际定义/重写的方法
            if name not in self.__class__.__dict__:
                continue

            # 先尝试当前函数自身的元数据
            meta = getattr(method, "_task_meta", None)
            if meta is None:
                # 回退：在 MRO 中查找父类定义的同名函数的元数据（允许子类实现但不重新装饰）
                meta = self._find_task_meta(name)

            if not meta:
                continue

            # 前缀使用子类文件名（小写），优先通过文件路径获取，失败回退到模块名
            try:
                prefix = Path(inspect.getfile(self.__class__)).stem.lower()
            except (TypeError, OSError):
                prefix = getattr(self.__class__, "__module__", "").split(".")[-1].lower()

            task_id = f"{prefix}_{name}"

            # 渲染 label/hint
            label = meta["label_template"].format(client_name=getattr(self.client, "name_cn", "未知"))
            hint = meta["hint_template"].format(client_name=getattr(self.client, "name_cn", "未知"))

            # 绑定实例方法并包装为返回 TaskResult
            bound = getattr(self, name)
            wrapped = self._task_wrapper_for(bound)

            tasks.append({
                "id": task_id,
                "label": label,
                "hint": hint,
                "func": wrapped  # 已包装，调用后总是返回 TaskResult
            })
        return tasks

    @staticmethod
    def make_task_result(
            success: bool = True,
            data: Optional[Dict[str, Any]] = None,
            message: str = "",
            error: Optional[str] = None,
            raw: Any = None
    ) -> TaskResult:
        """静态构造 TaskResult，子类可以直接返回 BaseTask.make_task_result(...)"""
        return TaskResult(success=success, data=data or {}, message=message, error=error, raw=raw)

    @staticmethod
    def ok(data: Optional[Dict[str, Any]] = None, message: str = "", raw: Any = None) -> TaskResult:
        """快速返回成功的 TaskResult"""
        return BaseTask.make_task_result(True, data, message, None, raw)

    @staticmethod
    def fail(message: str = "", error: Optional[str] = None, data: Optional[Dict[str, Any]] = None,
             raw: Any = None) -> TaskResult:
        """快速返回失败的 TaskResult"""
        return BaseTask.make_task_result(False, data, message, error, raw)
