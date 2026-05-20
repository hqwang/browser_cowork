https://b3sh6jivuw.feishu.cn/share/base/form/shrcnJAnk4pUjerGBOaWHTFiJIf 打开网址，进行如下操作：
是否涉及版本计划<Dropdown>：(自主迭代)
1. xqID<Dropdown>：{xqID}
2. 是否数据需求<Dropdown>：{xqType} (功能型,数据型,#N/A)
3. 模板名称<Dropdown>：(全流程)
4. Subo涉及的拆解<Table>：{suboList[]}，按照suboList逐个添加。
  - 节点序号<Dropdown>：{[].pointType}
  - 拆解工时估分PH<input>：{[].spendHour}
  - 节点负责人<Dropdown>：{[].pointPerson}
  - 节点名称<input>：{[].pointName}
输入：/Users/tyc/Desktop/input.txt，以上变量根据输入文件的值自主填充，Dropdown为下拉框，需要“点击-选择”；input为输入框，需要“输入文字”；Table为表格，需要逐一添加，每添加一个点击“添加一行-新增一行”。
