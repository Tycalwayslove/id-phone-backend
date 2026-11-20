# 静态数据

- `regions.json`：省级与地级行政区划（6 位代码，省 `440000`、市 `440100`）。直辖市没有下级“市”，`cities` 为空，按省级当作城市。
  来源：[modood/Administrative-divisions-of-China](https://github.com/modood/Administrative-divisions-of-China) v2.7.0 `dist/pc-code.json`（数据来自国家统计局），2026-11-19 导入。
  不含港澳台。`short` 是去掉“省/市/自治区”等后缀的简称，用于从服务商规格名称里识别地区（如“广州市社保证”“贵州身份证”）。
