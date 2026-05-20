写一个脚本输入：
- --name 开发名字集合(可选) ，用 ","分割。
- --name-list-file 支持指定人员列表文件 ，文件格式： 团队:人名1,人名2,人名3。
- -- start 起始时间(可选) ，使用yyyymmdd格式；--end 结束时间(可选) ，使用yyyymmdd格式。
- --min_ale sum(ale)大于此值(可选) ，--min_token sum(token)大于此值(可选)。--max_ale、-- max_token ，与前两者效果相反。
工作：
- 读取url为xxx的数据库 ，账号、密码默认值空白 ，后续填写。
- 按照name分组 ，取字段name, sum(ale) as ale_total, sum(token) as token_total。
- 查找name属于{开发名字集合} && dt >={起始时间} && dt <={结束时间} && ale_total满足{-- min_ale} or {--max_ale} && token_total满足{--min_token} or {--max_token}。
输出：
- 整个结果最前面添加一行 ，Cursor数据统计 [start-end] ，start和end为输入参数的mmdd格式。
- 多行文本 ，每行包含{name}, {ale}行, {token}(万 ，＜1万无小数点 ，反之一位小数)。参数包括-- name-list-file选项时 ，添加段落标题{团队}
- 通过 webhook[https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx] 发送飞书消息。
