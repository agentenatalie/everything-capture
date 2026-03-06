# 数据库问题：

- 在导入到 Notion 数据库时，我发现小红书下载的帖子和抖音下载的帖子似乎无法成功导入数据库。我发现这是因为我不知道为什么，系统甚至没有创建新的页面。此外，我还发现有些图片无法导入到数据库，而有些图片则可以。在 Notion 中，这些情况都是为什么呢？ 解决它

- 导入到obsidian的时候有些可以导入 有些不行 不知道为什么 很奇怪 然后有些时候还会同步失败: Obsidian API error: { "message": "Internal Server Error\nFailed to decode param 'HUMAN%203.0%20%E2%80%93%20A%20Map%20To%20Reach%20The%20Top%201%.md'", "errorCode": 50000 }

- 我发现，上传到数据库的时候，格式又不对了。就是之前做好的在一个页内插入的格式又不对了。我希望传到数据库的时候，也保持上传进来的这个图文混合的格式。

- 上传到obsidian的时候，你不仅给我上传了所有的东西，而且他还把所有的图片都单独上传上去了。反正就一上传就上传了一大堆文件，但是都被放在了EverythingCapture_Media里，我不太懂所以你判断这对不对，直接把text和image是否放在一个文件里会更好。 

- 动态检测数据库里是否还有内容 有些内容被放在数据库里以后又删除了 那就不能再是已同步状态

# 搜索问题：

- 现在的问题时搜索的时候出来的结果都是一致的，不管搜什么东西，出来的都是一样的结果。

- 搜索后就不需要再把“搜索资料库”和“从剪切板导入”这两个东西留在搜索页面了，可以隐藏。

- 我希望添加一个功能 就是如果输入的是：
    5.89 06/24 n@D.Hi OXz:/ 1.7亿阅读的“人生作弊码”，教你一天“重装你的人生系统” # 个人成长 # 认知觉醒 # 思维成长  https://v.douyin.com/cxyjLsymuhk/ 复制此链接，打开Dou音搜索，直接观看视频！
    或者
    51 【Jacksonpark个人转租我的纽约小屋❣️ - 9+1 | 小红书 - 你的生活兴趣社区】 😆 jZBT2V0Qtp9BsIY 😆 https://www.xiaohongshu.com/discovery/item/69a47473000000002203b019?source=webshare&xhsshare=pc_web&xsec_token=CBxCIirv_OrM07ik0KhiA-mmJh9SKBNv7fzqB5dnQzCbs=&xsec_source=pc_share
    那你不能识别成文字，而是自动识别里面的链接并capture