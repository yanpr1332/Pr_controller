# Premiere Controller

中文 | [English](README_EN.md)

Windows 本机 Premiere Pro 自动化控制器。代码、桥接、示例、测试与文档全部独立于 Adobe 安装文件。当前版本 0.2.0，原生验证环境为 Premiere Pro **26.0.1**；其他版本先运行能力检查和隔离测试。

## 环境与安装

Python 3.10+、Windows、已安装的 Premiere Pro。核心只使用 Python 标准库；照片装饰与 PDF 渲染可选安装 visual 扩展。

```powershell
python -m pip install -e ".[visual]"
$env:PREMIERE_EXE = 'D:\computer\Adobe\Premiere Pro\Adobe Premiere Pro 2026\Adobe Premiere Pro.exe'
pr-controller doctor
pr-controller install
```

安装是显式操作，会将桥接入口写入 Premiere 的 Startup 目录；构造 Python 对象不会修改 Adobe 安装目录。安装后保存并重开 PR。新版使用独立任务文件和桥接入口，不强制结束 PR。本机已停用旧版启动桥，清理后的目录与历史素材位置见 [本机目录说明](docs/LOCAL_LAYOUT.md)。

默认运行目录为用户 AppData/Local/PrController/runtime，可用 **PR_CONTROLLER_RUNTIME** 或 `Config(runtime=...)` 指定。当前这台机器的开发验证安装使用仓库下 **runtime-v2**；连接这个实例时使用相同配置。移动仓库后重新执行 install，以更新入口中的源码位置。

## 使用

```python
from pathlib import Path
from pr_controller import PremiereController, Config

c = PremiereController(config=Config(runtime=Path('runtime-v2').resolve()))
print(c.doctor())
print(c.capabilities())
print(c.timeline('主序列'))
print(c.shift_timeline(30, 5, sequence='主序列', dry_run=True))
```

保留旧公开方法，并提供稳定的 sequenceID、素材 nodeId、完整路径及素材箱路径选择。重名会报错。新结构化方法返回字典；旧兼容方法主要返回 status/op/data 列表，安全检查和部分 data 内容已升级，迁移说明见 [docs/MIGRATION.md](docs/MIGRATION.md)。

| 能力 | 入口 |
| --- | --- |
| 诊断、显式安装和连接 | doctor / install_bridge / connect |
| 独立任务与状态、取消尚未开始的任务 | submit / job_status / cancel_queued |
| 时间线、素材与离线清单 | timeline / catalog |
| 序列设置与明确追加轨道 | configure_sequence / ensure_tracks |
| 视频、音频或同步音画的指定轨道插入 | place_media |
| 带标记的整体顺延和预演 | shift_timeline |
| 批量参数和关键帧、时间坐标、缓动 | set_motion / animate |
| 画面完整显示或铺满 | fit_clip |
| 效果和转场、空隙过滤、本机名称处理 | add_video_effect / add_audio_effect / add_transition / add_audio_transition |
| 严格复制、移动、关联音画和批量操作 | clone_or_move / clone_av / clone_group |
| 项目快照和失败恢复 | backup_project / transaction |
| 原生 PNG 预览和直接导出、旧 AME 导出 | preview / export_direct / encode_sequence_ame |
| 照片墙、叠页和页面聚焦 | create_composition / build_photo_wall / build_page_fan |
| SRT/VTT/MD 与时间偏移 | pr_controller.subtitles |
| 注册字幕源、导入字幕轨、从源导出 | register_subtitle_source / export_subtitle_source |
| 图片、PDF 页面和媒体清单打包 | visual.photo_card / visual.pdf_pages / media.collect / media.probe |

## 编辑安全与行为

新高层编辑接口以事务保护主要修改：执行前保存当前项目并生成快照，失败时重开恢复后的项目。批量调用可用 `transaction()` 合并，减少重复保存。事务禁止任意 eval、打开其他工程、导出等无法由项目快照撤销的操作。复制恢复会核对参数和效果顺序，读不到或恢复不了的内容会报错；移动不会继续删除源片段。

原始脚本执行、`invoke()` 和旧版未迁移的低层操作属于高级入口。调用者可显式使用 transaction 包住受支持的修改；执行自动化期间避免同时手动编辑同一时间线。普通成功编辑后仍建议调用 save_project 保存最终状态。

关键帧支持 clip/source/sequence 三种时间坐标。旧 opacity 接口默认 source，以保留历史语义；新 animate 默认 clip。非线性曲线复制在可求值时按渲染帧采样重建；它保留当前帧率下的参数轨迹，不保留原始贝塞尔手柄。无法读取的插件参数会拒绝复制。

超时不等于取消。任务 ID 和运行记录保留在 runtime；长导出可增加 timeout，或用 submit 提交、job_status 查询。原生直接导出阻塞期间不能安全强制取消；cancel_queued 只取消尚未被 PR 领取的任务。

## 字幕边界

离线字幕支持 SRT、VTT、MD 解析、输出和分段时间偏移。注册源可生成 SRT 并创建 PR 字幕轨，随后按登记的源文件导出或改时间。Premiere 26 的 ExtendScript 未完整公开字幕正文读写；检测不到正文 API 时明确报错，绝不把 clip 名称当作字幕正文。手工在 PR 修改过的字幕，请重新提供字幕源；源文件导出不会假称回读了这些修改。

## 验证

```powershell
python -m unittest discover -s tests -v
python tools/generate_fixtures.py runtime/fixtures --wsl
python tools/native_smoke.py --runtime runtime-v2 --workspace runtime-v2/native-smoke --media-directory runtime/fixtures --visual --preset "本机 H.264 导出预设.epr"
```

原生测试只允许关闭生产工程后，在指定测试目录创建新工程；使用合成视频和静音音轨。CI 运行不依赖 Adobe 的离线测试。实际结果见 [docs/VALIDATION.md](docs/VALIDATION.md)，全部功能对应清单见 [docs/FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md)。历史实现验证记录在 docs/legacy-validation.md。

本仓库不包含 Adobe 软件、商业插件、用户工程和录音。本项目采用 [MIT License](LICENSE)。Adobe 软件和第三方依赖分别遵循各自的许可条款。
