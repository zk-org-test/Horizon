---
layout: default
title: "Horizon Summary: 2026-05-10 (ZH)"
date: 2026-05-10
lang: zh
---

> From 12 items, 4 important content pieces were selected

---

1. [Bun 实验性 Rust 重写称 Linux x64 glibc 测试兼容率达 99.8%](#item-1) ⭐️ 8.0/10
2. [FreeBSD execve() 漏洞可导致本地提权](#item-2) ⭐️ 8.0/10
3. [Let-go：用 Go 实现的类 Clojure 运行时，冷启动约 7ms](#item-3) ⭐️ 8.0/10
4. [法国考虑可能削弱端到端加密消息的措施](#item-4) ⭐️ 8.0/10

---

<a id="item-1"></a>
## [Bun 实验性 Rust 重写称 Linux x64 glibc 测试兼容率达 99.8%](https://twitter.com/jarredsumner/status/2053047748191232310) ⭐️ 8.0/10

Bun 团队称其实验性的 Zig→Rust 重写在 Linux x64 glibc 上已达到约 99.8% 的测试套件兼容率。该进展引发大量讨论，焦点包括该移植是否会真正落地、AI 辅助翻译在其中的作用，以及对长期稳定性与性能的影响。 Bun 作为备受关注的 JavaScript 运行时，如果接近完成的 Rust 移植最终进入主线，可能会改变其可靠性表现以及社区贡献者生态。与此同时，这也展示了在 LLM 辅助下大型系统重写的速度上限，可能让“算力与产出”更直接地影响竞争格局。 所称 99.8% 的数据限定在 Linux x64 且使用 glibc 的构建环境下，因此并不必然代表其它平台或不同 libc 环境的结果。Bun 开发者也提醒该分支仍属实验性质，未必已形成可用的完整版本，并且存在很大概率会被整体放弃而不是合并。

hackernews · heldrida · May 9, 10:12 · [社区讨论](https://news.ycombinator.com/item?id=48073680)

**背景**: Bun 是一个 JavaScript 运行时，常被视为 Node.js 与 Deno 的替代选择，主打高性能以及更一体化的开发工具链。Deno 通常被认为在架构与默认实践上与 Node.js 有差异，例如依赖管理工作流不同。在 Linux 上，glibc 是标准的 GNU C Library，提供大量面向操作系统的基础例程，因此“Linux x64 glibc”意味着面向多数采用 glibc 的发行版的常见二进制兼容目标。Rust 与 Zig 都用于系统编程，但 Rust 更强调通过更严格的编译器检查在编译期提供内存安全保障，而 Zig 则更强调显式控制与更手动的内存管理方式。

<details><summary>参考链接</summary>
<ul>
<li><a href="https://betterstack.com/community/guides/scaling-nodejs/nodejs-vs-deno-vs-bun/">Node.js vs Deno vs Bun: Comparing JavaScript Runtimes | Better Stack Community</a></li>
<li><a href="https://linuxfromscratch.org/lfs/view/stable/chapter05/glibc.html">5.5. Glibc -2.42</a></li>
<li><a href="https://blog.logrocket.com/comparing-rust-vs-zig-performance-safety-more/">Comparing Rust vs . Zig : Performance, safety , and... - LogRocket Blog</a></li>

</ul>
</details>

**社区讨论**: 评论区一部分人对重写速度感到震撼，并将其归因于大量 LLM/token 的使用；另一部分人则质疑其可持续性、可维护性以及最终是否会发布。有人认为 Rust 版本可能相对 Zig 减少崩溃与内存问题，但也有人指出如果大量依赖 `unsafe`，收益会被削弱，而且该分支本就未承诺落地、随时可能被丢弃。

**标签**: `#bun`, `#rust`, `#javascript-runtime`, `#software-porting`, `#llm-assisted-development`

---

<a id="item-2"></a>
## [FreeBSD execve() 漏洞可导致本地提权](https://www.freebsd.org/security/advisories/FreeBSD-SA-26:13.exec.asc) ⭐️ 8.0/10

FreeBSD 发布了安全公告 FreeBSD-SA-26:13.exec，警告一个与 execve() 相关的漏洞可导致本地权限提升。与 CVE-2026-7270 相关的第三方文章补充了利用细节和修复/缓解信息。 execve() 是启动程序的核心系统调用，因此这里的缺陷往往触达面很广，可能把普通本地权限直接提升到 root。对运行多用户主机、以及依赖 setuid-root 程序的环境来说，本地提权属于影响极大的安全失效场景。 第三方复现文章指出，FreeBSD 的运行时链接器在处理 LD_PRELOAD 前会检查 issetugid()，如果该检查结果不正确，可能导致不安全的环境变量处理并形成提权链路。社区讨论强调这类问题可能源自非常隐蔽的运算符优先级错误（通过补充括号修复），但其安全影响却极其关键。

hackernews · Deeg9rie9usi · May 9, 20:31 · [社区讨论](https://news.ycombinator.com/item?id=48077971)

**背景**: exec（包括 execve()）会用新程序替换当前进程的程序映像，在保留进程上下文的同时加载并运行新的可执行文件。在类 Unix 系统中，setuid-root 程序和 LD_PRELOAD 这类动态链接机制会被严格限制，因为一旦允许不可信环境变量影响特权程序的加载过程，就可能导致权限提升。FreeBSD 使用 issetugid() 等检查，让运行时链接器在进程具备提升权限时忽略危险的环境设置。

<details><summary>参考链接</summary>
<ul>
<li><a href="https://blog.calif.io/p/cve-2026-7270-how-i-get-root-on-freebsd">CVE-2026-7270: How I Get Root on FreeBSD with a Shell Script</a></li>
<li><a href="https://en.wikipedia.org/wiki/Exec_(system_call)">exec ( system call ) - Wikipedia</a></li>
<li><a href="https://news.ycombinator.com/item?id=48077971">FreeBSD : Local Privilege Escalation via Execve () | Hacker News</a></li>

</ul>
</details>

**社区讨论**: 评论主要围绕补丁 diff 中通过添加括号修复的运算符优先级错误展开，有人建议在项目中禁止不加括号的混合运算以减少此类安全问题。也有人分享了 Calif.io 的详细复现文章（以及一个 AI 生成的可用 exploit 写作与提示词），并指出该问题在 15.0R-p7 中已修复，另外还有关于“exeCVE”的玩笑式评论。

**标签**: `#FreeBSD`, `#security-advisory`, `#privilege-escalation`, `#execve`, `#CVE`

---

<a id="item-3"></a>
## [Let-go：用 Go 实现的类 Clojure 运行时，冷启动约 7ms](https://github.com/nooga/let-go) ⭐️ 8.0/10

Let-go 是一个用纯 Go 编写、与 JVM 版 Clojure 约 90%兼容的语言运行时，可发布为约 10MB 的静态二进制，并声称冷启动约 7ms。它提供 nREPL 服务器支持，并主打可嵌入到 Go 程序中，实现跨语言边界的便捷互操作。 对于希望摆脱 JVM 部署的 Clojure 开发者来说，这类快速启动、体积小的二进制运行时更适合 CLI 与服务场景，能显著改善冷启动与分发复杂度。它兼容 nREPL 工具链也意味着即便不跑在 JVM 上，很多既有编辑器工作流仍可延续。 在实现上，let-go 采用手写编译器与栈式 VM，并支持 AOT 模式生成可移植的字节码产物以及独立可执行文件（运行时+字节码）。它并非 JVM Clojure 的直接替代品：不支持加载 JAR，也缺少 Java API，现有项目大概率需要修改才能运行。

hackernews · marcingas · May 9, 17:52 · [社区讨论](https://news.ycombinator.com/item?id=48076815)

**背景**: 大多数 Clojure 代码运行在 JVM 上，能够深度使用 Java 生态库，但启动开销通常比原生二进制更高。Babashka 是常见的快速启动 Clojure 脚本运行时，其核心基于 SCI（Small Clojure Interpreter）这一可配置解释器，并常与 GraalVM 的原生打包路径相关联。nREPL 是一种基于套接字的“网络 REPL”协议，Clojure 常用编辑器与工具通过其中间件与消息机制，在运行中的进程里进行代码求值与交互。

<details><summary>参考链接</summary>
<ul>
<li><a href="https://nrepl.org/nrepl/index.html">nREPL :: nREPL</a></li>
<li><a href="https://github.com/babashka/babashka">GitHub - babashka/babashka: Native, fast starting Clojure interpreter for scripting · GitHub</a></li>
<li><a href="https://github.com/babashka/sci">GitHub - babashka/ sci : Configurable Clojure /Script interpreter ...</a></li>

</ul>
</details>

**社区讨论**: 评论区整体对这种“无 JVM、启动极快”的类 Clojure 运行时比较兴奋，并将其与 Janet、Fennel（Lua VM）以及 Joker 等替代方案做对比。也有人补充了围绕 Glojure/Gloat 的相关工具生态并关注互操作与协作进展，同时有评论指出 README 里冷启动数据表述存在小出入（7ms 与 6ms）。

**标签**: `#programming-languages`, `#clojure`, `#go`, `#language-runtime`, `#developer-tools`

---

<a id="item-4"></a>
## [法国考虑可能削弱端到端加密消息的措施](https://reclaimthenet.org/france-moves-to-break-encrypted-messaging) ⭐️ 8.0/10

法国正在考虑可能会实质性削弱或限制加密消息的政策措施，引发外界担忧主流应用中的端到端加密（E2EE）会被破坏。相关动向也引起了关于强制访问加密通信会带来哪些安全与社会后果的讨论。 削弱 E2EE 通常会降低隐私并增加网络安全风险，因为任何被强制加入的访问机制都可能被攻击者滥用，而不只是在合法调查中使用。由于加密消息已广泛用于个人、商业与政治沟通，国家或欧盟层面的变化可能影响大量用户与服务提供商。 端到端加密的设计目标是只有发送者与接收者持有密钥，这意味着服务提供商在不改变系统信任模型的情况下无法读取消息内容。以“后门”或强制接入为名的方案通常会引入系统性脆弱点；社区讨论还指出公众常误解哪些应用默认提供 E2EE（例如 Telegram 默认并非 E2EE）。

hackernews · Cider9986 · May 9, 22:14 · [社区讨论](https://news.ycombinator.com/item?id=48078811)

**背景**: 端到端加密（E2EE）是一种通信设计，只有通信双方的终端设备能够解密消息，中间环节（包括服务提供商）并不持有解密密钥。“加密后门”是指任何允许第三方绕过或破坏加密的内置机制；即便初衷是用于合法取证，也会扩大攻击面并可能被滥用。在政策讨论中，有时会提出客户端扫描等替代方案，但这会把内容检查转移到用户设备上，同样带来安全与隐私风险。

<details><summary>参考链接</summary>
<ul>
<li><a href="https://en.wikipedia.org/wiki/End-to-end_encryption">End-to-end encryption - Wikipedia</a></li>
<li><a href="https://proton.me/learn/encryption/glossary/encryption-backdoor">What is an encryption backdoor and why is it risky? | Proton</a></li>
<li><a href="https://www.internetsociety.org/resources/doc/2020/fact-sheet-client-side-scanning/">Fact Sheet: Client-Side Scanning - Internet Society</a></li>

</ul>
</details>

**社区讨论**: 评论者普遍嘲讽“禁止乱码”的可行性，并质疑当局究竟如何识别传输中的内容是否加密。也有人认为政策制定者会无视专家警告，直到出现引人注目的重大事故才会回头；另有评论纠正称 Telegram 默认并非端到端加密（而 Signal 是），反映公共讨论中反复出现的认知混乱。

**标签**: `#encryption`, `#privacy`, `#cybersecurity-policy`, `#end-to-end-encryption`, `#EU-regulation`

---