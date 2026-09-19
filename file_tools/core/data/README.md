# data/

- `TomatoNovelDownloader.exe`：内置的番茄小说下载后端（官方 API 链路：设备注册 →
  内容密钥 → 批量明文正文），以 `--server` Web UI 模式被本工具调用。
  来源：https://github.com/zhongbai2333/Tomato-Novel-Downloader （v2.4.15，MIT 许可，
  见 TomatoNovelDownloader-LICENSE.txt）。
- `TomatoNovelDownloader-LICENSE.txt`：上游 MIT 许可文本。

本目录其余文件随 exe 一并打包；运行时工作目录（config/output）在系统临时目录。
- `hls.min.js`：浏览器模式预览用的 HLS 播放器库（hls.js v1.5.20，Apache-2.0 许可，
  许可声明见文件头部注释），由本地预览代理的播放页加载，不依赖外部 CDN。
