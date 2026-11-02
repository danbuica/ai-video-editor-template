/**
 * Note: When using the Node.JS APIs, the config file
 * doesn't apply. Instead, pass options directly to the APIs.
 *
 * All configuration options: https://remotion.dev/docs/config
 */

import { Config } from "@remotion/cli/config";

Config.setRspack(true);
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(100);
// crf is passed per render (--crf=… for x264); leaving it unset lets --hardware-acceleration + --video-bitrate work
Config.setPixelFormat("yuv420p");
Config.setOverwriteOutput(true);
// Serve ../projects as the public folder: staticFile("<project>/out/talking_cut.mp4")
Config.setPublicDir("../projects");
