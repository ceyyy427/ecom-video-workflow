# 文字表现与手动 Prompt 采用依据

核对日期：2026-10-22。生产仍使用已锁定的 Remotion 4.0.519 / React 19.2.0，未新增运行依赖或云调用。

| 来源 | 固定依据、许可 | 本轮决定 |
|---|---|---|
| Anime.js | `juliangarnier/anime@01b81be1df6843ccfe0a71c0699a746bf740dd77`，MIT；LICENSE 保存在 `typography/Animejs-LICENSE.txt` | 采用 splitText 文档中的分组、遮罩、错峰揭示方法；以现有 Remotion 帧时钟实现，未复制动画引擎、DOM 拆字或计时器代码 |
| Remotion | 现有锁文件 4.0.519；其自身许可适用，不能笼统称整包为 MIT | 复用 `spring` / `interpolate` / 本机渲染。只由 frame/fps 驱动，不依赖 CSS 动画、网络字体或随机时间 |
| video-shotcraft | 已有 Apache-2.0 固定版本 `43bd349a136651865ecfa6ea1cf012f6e957d304` | 保留完整本机参考索引及来源，手动选择只映射到有限配方，不运行网页 Prompt 代码，不使用样例品牌媒体 |
| taste-skill | 已安装 MIT 版本，沿用 `.taste-skill/direction.json` 的 framed-sheet / builder | 参考库采用同一侧栏、双栏工作面、按需展开来源。用户禁止 Computer Use，因此未执行浏览器巡检或截图；使用 DOM 事件、结构与样式检查 |
| React Bits | 官方 LICENSE.md 为 MIT + Commons Clause | 未采用或复制组件。其出售/分发限制不适合直接嵌入本项目客户软件包，不能按普通 MIT 处理 |

官方说明：[Anime.js splitText](https://animejs.com/documentation/text/splittext/)、[固定许可证](https://github.com/juliangarnier/anime/blob/01b81be1df6843ccfe0a71c0699a746bf740dd77/LICENSE.md)、[Remotion spring](https://www.remotion.dev/docs/spring)、[React Bits 许可](https://github.com/DavidHDev/react-bits/blob/main/LICENSE.md)。

资源影响：字体继续本机测量为透明 PNG；每镜最多三个文字分组，三种有限样式，不新增模型/GPU内存需求。不下载商业字体。首次切换软件版本会使渲染引擎缓存失效；同一软件版本内单镜修改仍独立缓存。

参考不等于逐条复制上游效果；新的文字表现是项目原创适配。许可证声明不覆盖客户素材授权。
