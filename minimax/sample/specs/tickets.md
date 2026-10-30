# 工单查询规格 v1

## R-001 归档可见性 archived includeArchived
listTickets 默认排除 archived 为 true 的工单。只有 options.includeArchived 严格等于 true 时才包含归档工单。
未传 options、空 options、includeArchived 为 false、字符串 "true"、数字 1、null 时均隐藏归档工单。
未设置 archived 字段的历史工单仍视为未归档。

## R-002 筛选组合 status tag
includeArchived 与原有 status 和 tag 过滤取交集。status 只允许 open、in_progress、closed；未指定或为空字符串时不过滤状态。
不合法的非空 status 抛出 RangeError。tag 使用精确匹配。

## R-003 兼容性 limit order immutable
结果保持输入顺序，不修改输入数组、工单对象或 options。limit 是非负整数，未指定则不限制；0 返回空数组。
不合法 limit 抛出 RangeError。空输入返回空数组。显式包含归档时，原有查询行为保持。

## R-099 非本任务：工单写入
createTicket 必须提供非空标题。本任务不修改工单写入、身份认证和通知。
