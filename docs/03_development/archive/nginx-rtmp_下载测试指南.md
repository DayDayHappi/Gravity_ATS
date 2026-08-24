# nginx-rtmp-mod 下载测试指南

在 Ubuntu 上安装并验证 Nginx + RTMP 模块,搭建 RTMP 推流/拉流服务端。

---

## 1. 安装 Nginx 与 RTMP 模块

```bash
sudo apt update
sudo apt install -y nginx libnginx-mod-rtmp
```

`libnginx-mod-rtmp` 是 Ubuntu 官方仓库自带的 RTMP 支持包,无需自己编译。

## 2. 检查 Nginx 本体

先不改配置,确认基础服务正常。

```bash
nginx -v          # 看版本
sudo nginx -t     # 校验配置语法
```

正常输出:

```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

检查服务状态:

```bash
systemctl status nginx --no-pager
```

重点看 `Active: active (running)`。

再确认监听端口:

```bash
sudo ss -lntp | grep nginx
```

此时至少应看到 HTTP 的 `LISTEN ... :80 ...`。

## 3. 检查 RTMP 模块是否已加载

> 关键:Nginx 能启动 ≠ RTMP 模块可用。

```bash
ls -l /usr/lib/nginx/modules/ngx_rtmp_module.so
```

官方包安装后该文件应存在。再确认加载声明:

```bash
ls -l /etc/nginx/modules-enabled/

grep -R "ngx_rtmp_module" \
    /etc/nginx/modules-enabled \
    /usr/share/nginx/modules-available \
    2>/dev/null
```

正常能看到类似:

```
load_module modules/ngx_rtmp_module.so;
```

## 4. 配置 RTMP Server

新建独立配置文件:

```bash
sudo nano /etc/nginx/rtmp.conf
```

写入:

```nginx
rtmp {
    server {
        listen 1935;
        chunk_size 4096;

        application live {
            live on;
            record off;
        }
    }
}
```

然后在主配置中引入:

```bash
sudo nano /etc/nginx/nginx.conf
```

你会看到大概这种结构:

```nginx
include /etc/nginx/modules-enabled/*.conf;

user www-data;

events {
    ...
}

http {
    ...
}
```

在 `events {}` 与 `http {}` **之间**加入:

```nginx
include /etc/nginx/rtmp.conf;
```

最终类似:

```nginx
include /etc/nginx/modules-enabled/*.conf;

user www-data;

events {
    worker_connections 768;
}

include /etc/nginx/rtmp.conf;

http {
    ...
}
```

> 注意:`rtmp` 配置块必须放在 `http {}` 之外,和 `events`/`http` 平级。放进 `http {}` 里会报 `"rtmp" directive is not allowed here`。

## 5. 检查配置并重启

```bash
sudo nginx -t
```

只有看到 `syntax is ok` / `test is successful` 才继续:

```bash
sudo systemctl restart nginx
systemctl status nginx --no-pager
```

再看 1935 端口:

```bash
sudo ss -lntp | grep 1935
```

正常应出现:

```
LISTEN 0 511 0.0.0.0:1935 0.0.0.0:* users:(("nginx",...))
```

到这里,链路 `Nginx → ngx_rtmp_module → TCP 1935` 已就绪。

## 6. 真正验证 RTMP(不要只看端口)

用 FFmpeg 生成测试画面推给 Nginx:

```bash
ffmpeg \
    -re \
    -f lavfi \
    -i testsrc=size=1280x720:rate=30 \
    -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -pix_fmt yuv420p \
    -f flv \
    rtmp://127.0.0.1/live/test
```

此时链路:

```
FFmpeg ──RTMP PUSH──▶ 127.0.0.1:1935 ──▶ Nginx RTMP ──▶ application: live / stream: test
```

另开一个终端拉流:

```bash
ffplay rtmp://127.0.0.1/live/test
```

若看到 FFmpeg 的彩色测试画面,即证明整条链路完全打通:

```
FFmpeg PUSH → RTMP → Nginx → RTMP → ffplay
```

---

## 要点回顾

| 环节 | 关键点 |
|------|--------|
| 安装 | `libnginx-mod-rtmp` 官方包,免编译 |
| 模块加载 | 必须确认 `load_module modules/ngx_rtmp_module.so;`,Nginx 能启动不代表模块可用 |
| 配置位置 | `rtmp {}` 放在 `http {}` 外、与 `events` 平级 |
| 验证 | 端口 LISTEN 只是半程,务必用 ffmpeg 推流 + ffplay 拉流闭环确认 |

---

## 附:使用项目内置 FFmpeg(本仓库)

本仓库已内置静态 FFmpeg(`tools/ffmpeg/`),不依赖系统安装。第 6 步的两条命令可直接换成:

```bash
# 推测试画面(项目内置 ffmpeg)
./tools/ffmpeg/ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 \
    -c:v libx264 -preset ultrafast -tune zerolatency \
    -pix_fmt yuv420p -f flv rtmp://127.0.0.1/live/test

# 拉流看画面(项目内置 ffplay)
./tools/ffmpeg/ffplay rtmp://127.0.0.1/live/test
```

与第 6 步的区别仅在于:命令前加了 `./tools/ffmpeg/` 前缀,使用项目内置二进制,而非系统 PATH 中的 ffmpeg/ffplay。
