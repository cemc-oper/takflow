作业渲染
========

标准构建的 job 阶段使用这些模块。应用也可通过 Python 入口单独渲染作业。构建上下文和产物登记见 :doc:`../guide/build`。

takflow.jobs.render
-------------------

选择模板、生成日志路径并写出作业。旧代码中的目录渲染、单文件渲染和日志路径函数都从此处导入。
独立渲染默认使用 ``takflow vunknown`` 文件头。应用可以在渲染调用外使用
``takflow.build_info.build_info_scope(lines)`` 指定文件头，退出作用域后恢复外层品牌。

.. automodule:: takflow.jobs.render
   :members:

takflow.jobs.headers
--------------------

生成 ORVIX 和原生 Slurm 资源头。直接使用 Jinja 的调用方可将
``RESOURCE_TEMPLATE_HELPERS`` 注册到模板环境，并提供工作流配置。

.. automodule:: takflow.jobs.headers
   :members:

takflow.jobs.scripts
--------------------

目录渲染器为模板提供 ``include_raw`` 和 ``invoke_script``。
``include_raw`` 读取片段，``invoke_script`` 根据 ``script_invoke_mode``
选择外部调用或内嵌。资源声明和提交命令见 :doc:`backends`。
