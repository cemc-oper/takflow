"""
钩子系统基础设施。

提供通用的钩子注册表基类和工厂函数。
"""
from typing import Callable, Dict, List, Tuple, Any, Optional, TypeVar, Generic
from enum import Enum
import logging


logger = logging.getLogger(__name__)


# 类型变量
T = TypeVar('T')  # 上下文类型
R = TypeVar('R')  # 返回值类型
HookPointType = TypeVar('HookPointType', bound=Enum)

# 钩子函数类型
HookFunction = Callable[[Any], Any]


def _get_hook_name(hook_point) -> str:
    """
    将钩子点转换为字符串名称
    
    Parameters
    ----------
    hook_point : Enum or str
        钩子点（字符串枚举或字符串）
        
    Returns
    -------
    str
        钩子点的字符串名称
    """
    return hook_point.value if isinstance(hook_point, Enum) else str(hook_point)


class BaseHookRegistry(Generic[T, R]):
    """
    通用钩子注册表基类
    
    管理钩子的注册、执行和查询。支持优先级控制和错误处理。
    
    Type Parameters
    ---------------
    T : 上下文类型
    R : 钩子函数返回值类型
    
    Examples
    --------
    >>> class MyRegistry(BaseHookRegistry[MyContext, str]):
    >>>     _instance = None
    >>>     
    >>>     @classmethod
    >>>     def get_instance(cls):
    >>>         if cls._instance is None:
    >>>             cls._instance = cls()
    >>>         return cls._instance
    """
    
    def __init__(self):
        self._hooks: Dict[str, List[Tuple[int, Callable[[T], R]]]] = {}
    
    def register(
        self, 
        hook_point: HookPointType, 
        func: Callable[[T], R], 
        priority: int = 100
    ) -> None:
        """
        注册钩子函数
        
        Parameters
        ----------
        hook_point : Enum
            钩子点（字符串枚举）
        func : Callable[[T], R]
            钩子函数
        priority : int, optional
            优先级，数字越小越先执行，默认 100
            建议范围：
            - 0-49: 高优先级
            - 50-99: 中优先级
            - 100+: 低优先级
        """
        hook_name = _get_hook_name(hook_point)
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
        
        self._hooks[hook_name].append((priority, func))
        self._hooks[hook_name].sort(key=lambda x: x[0])
        
        logger.debug(
            f"Registered hook '{func.__name__}' at '{hook_name}' with priority {priority}"
        )
        
    def execute(
        self, 
        hook_point: HookPointType, 
        context: T,
        stop_on_error: bool = True
    ) -> List[R]:
        """
        执行钩子点上的所有钩子函数
        
        按优先级顺序执行所有注册在该钩子点的函数。
        
        Parameters
        ----------
        hook_point : Enum
            钩子点
        context : T
            钩子上下文
        stop_on_error : bool, optional
            是否在遇到错误时停止执行，默认 True
            
        Returns
        -------
        List[R]
            所有钩子函数的返回值列表
            
        Raises
        ------
        Exception
            如果 stop_on_error=True 且钩子执行失败
        """
        hook_name = _get_hook_name(hook_point)
        if hook_name not in self._hooks:
            logger.debug(f"No hooks registered at '{hook_name}'")
            return []
        
        logger.info(f"Executing {len(self._hooks[hook_name])} hook(s) at '{hook_name}'")
        
        results = []
        for priority, func in self._hooks[hook_name]:
            try:
                logger.debug(f"Executing hook '{func.__name__}' (priority={priority})")
                result = func(context)
                results.append(result)
                logger.debug(f"Hook '{func.__name__}' completed successfully")
            except Exception as e:
                error_msg = f"Error executing hook '{func.__name__}' at '{hook_name}': {e}"
                logger.error(error_msg, exc_info=True)
                
                if stop_on_error:
                    raise
                else:
                    logger.warning(f"Continuing execution despite error in '{func.__name__}'")
        
        return results
    
    def unregister(self, hook_point: HookPointType, func: Callable[[T], R]) -> bool:
        """
        注销钩子函数
        
        Parameters
        ----------
        hook_point : Enum
            钩子点
        func : Callable[[T], R]
            要注销的钩子函数
            
        Returns
        -------
        bool
            是否成功注销
        """
        hook_name = _get_hook_name(hook_point)
        if hook_name not in self._hooks:
            return False
        
        original_count = len(self._hooks[hook_name])
        self._hooks[hook_name] = [
            (priority, f) for priority, f in self._hooks[hook_name]
            if f != func
        ]
        new_count = len(self._hooks[hook_name])
        
        if new_count == 0:
            del self._hooks[hook_name]
        
        return original_count > new_count
                
    def has_hooks(self, hook_point: HookPointType) -> bool:
        """
        检查某个钩子点是否有注册的钩子。

        Parameters
        ----------
        hook_point : Enum
            钩子点。

        Returns
        -------
        bool
            是否有注册的钩子。
        """
        hook_name = _get_hook_name(hook_point)
        return hook_name in self._hooks and len(self._hooks[hook_name]) > 0
    
    def count_hooks(self, hook_point: Optional[HookPointType] = None) -> int:
        """
        统计钩子数量。

        Parameters
        ----------
        hook_point : Enum, optional
            钩子点，为 None 时统计所有钩子。

        Returns
        -------
        int
            钩子数量。
        """
        if hook_point is not None:
            hook_name = _get_hook_name(hook_point)
            return len(self._hooks.get(hook_name, []))
        return sum(len(hooks) for hooks in self._hooks.values())
    
    def clear(self, hook_point: Optional[HookPointType] = None) -> None:
        """
        清除钩子。

        Parameters
        ----------
        hook_point : Enum, optional
            钩子点，为 None 时清除所有钩子。
        """
        if hook_point is None:
            self._hooks.clear()
            logger.info("Cleared all hooks")
        else:
            hook_name = _get_hook_name(hook_point)
            self._hooks.pop(hook_name, None)
            logger.info(f"Cleared hooks at '{hook_name}'")
            
    def list_hooks(
        self, 
        hook_point: Optional[HookPointType] = None
    ) -> Dict[str, List[Tuple[str, int]]]:
        """
        列出所有注册的钩子。

        Parameters
        ----------
        hook_point : Enum, optional
            钩子点，为 None 时列出所有钩子。

        Returns
        -------
        dict[str, list[tuple[str, int]]]
            钩子名称和优先级的映射。
        """
        if hook_point is not None:
            hook_name = _get_hook_name(hook_point)
            if hook_name in self._hooks:
                return {
                    hook_name: [
                        (func.__name__, priority) 
                        for priority, func in self._hooks[hook_name]
                    ]
                }
            return {}
        
        return {
            hook_name: [
                (func.__name__, priority) 
                for priority, func in funcs
            ]
            for hook_name, funcs in self._hooks.items()
        }
    
    def get_hook_points(self) -> List[str]:
        """
        获取所有已注册钩子的钩子点列表。

        Returns
        -------
        list[str]
            钩子点名称列表。
        """
        return list(self._hooks.keys())


def create_hook_decorator(registry_getter: Callable[[], BaseHookRegistry]):
    """
    创建钩子注册装饰器的工厂函数
    
    Parameters
    ----------
    registry_getter : Callable[[], BaseHookRegistry]
        获取注册表实例的函数
        
    Returns
    -------
    Callable
        装饰器工厂函数
        
    Examples
    --------
    >>> register_hook = create_hook_decorator(get_registry)
    >>> @register_hook(MyHookPoint.BEFORE, priority=50)
    >>> def my_hook(ctx): pass
    """
    def decorator_factory(hook_point, priority: int = 100):
        def decorator(func):
            registry_getter().register(hook_point, func, priority)
            return func
        return decorator
    return decorator_factory
