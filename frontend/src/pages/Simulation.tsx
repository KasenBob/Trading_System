import { useState, useEffect, useCallback } from 'react'
import {
  Card, Tabs, Table, Button, Form, InputNumber, Select, AutoComplete, Switch,
  Statistic, Row, Col, Tag, Typography, App, Spin, Modal, Empty, Descriptions,
} from 'antd'
import {
  RiseOutlined, FallOutlined, MinusOutlined, DollarOutlined,
  ShoppingCartOutlined, ReloadOutlined, PlusOutlined, DeleteOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { api } from '../services/api'

const { Title, Text } = Typography

function pctClr(v: number | null) { return v == null ? '#999' : v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : '#999' }
function fmt(v: number | null | undefined, d = 2) { return v == null ? '-' : v.toFixed(d) }
function fmtMoney(v: number | null | undefined) {
  if (v == null) return '-'
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return v.toFixed(2)
}

export default function Simulation() {
  const { message } = App.useApp()
  const [account, setAccount] = useState<any>(null)
  const [positions, setPositions] = useState<any[]>([])
  const [totalAsset, setTotalAsset] = useState(0)
  const [totalPnl, setTotalPnl] = useState(0)
  const [totalPnlPct, setTotalPnlPct] = useState(0)
  const [marketValue, setMarketValue] = useState(0)
  const [availableCash, setAvailableCash] = useState(0)
  const [transactions, setTransactions] = useState<any[]>([])
  const [snapshots, setSnapshots] = useState<any[]>([])
  const [indexData, setIndexData] = useState<any[]>([])
  const [statsData, setStatsData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const [orderCode, setOrderCode] = useState('')
  const [orderName, setOrderName] = useState('')
  const [orderDirection, setOrderDirection] = useState<'buy' | 'sell'>('buy')
  const [orderPrice, setOrderPrice] = useState<number | null>(null)
  const [orderQty, setOrderQty] = useState(100)
  const [orderLoading, setOrderLoading] = useState(false)
  const [watchlist, setWatchlist] = useState<any[]>([])
  const [activeTab, setActiveTab] = useState('order')
  const [resetOpen, setResetOpen] = useState(false)
  const [resetCapital, setResetCapital] = useState<number>(100000)
  const [orderStrategy, setOrderStrategy] = useState<string | undefined>(undefined)
  const [strategies, setStrategies] = useState<any[]>([])
  const [autoItems, setAutoItems] = useState<any[]>([])
  const [autoLogs, setAutoLogs] = useState<any[]>([])
  const [runLoading, setRunLoading] = useState(false)
  const [addAutoOpen, setAddAutoOpen] = useState(false)
  const [addAutoCode, setAddAutoCode] = useState('')
  const [addAutoName, setAddAutoName] = useState('')
  const [addAutoStrategy, setAddAutoStrategy] = useState<number | undefined>(undefined)
  const [addAutoPrice, setAddAutoPrice] = useState<number | null>(null)
  const [addAutoQuantity, setAddAutoQuantity] = useState<number>(100)
  const [addAutoLoading, setAddAutoLoading] = useState(false)
  const [autoOptions, setAutoOptions] = useState<any[]>([])
  const [removeAutoOpen, setRemoveAutoOpen] = useState(false)
  const [removeAutoPrice, setRemoveAutoPrice] = useState<number | null>(null)
  const [removeAutoItem, setRemoveAutoItem] = useState<any>(null)

  const loadWatchlist = useCallback(async () => {
    try {
      const { data } = await api.get('/watchlist')
      setWatchlist(data.data ?? [])
    } catch { /* 忽略：无自选股不影响下单 */ }
  }, [])

  useEffect(() => { loadWatchlist() }, [loadWatchlist])

  // 加载策略列表（供下单时标记使用）
  useEffect(() => {
    (async () => {
      try { const { data } = await api.get('/strategy'); setStrategies(data.data ?? []) } catch { /* 静默 */ }
    })()
  }, [])


  const loadData = useCallback(async () => {
    try {
      const [accR, posR, txnR, snapR, idxR, statsR] = await Promise.all([
        api.get('/trade/account'), api.get('/trade/positions'),
        api.get('/trade/transactions'), api.get('/trade/snapshots'),
        api.get('/market/index/sh000300'), api.get('/trade/stats'),
      ])
      const a = accR.data.data; setAccount(a); setAvailableCash(a.available_cash)
      const p = posR.data.data
      setPositions(p.positions); setTotalAsset(p.total_asset); setTotalPnl(p.total_pnl)
      setTotalPnlPct(p.total_pnl_pct); setMarketValue(p.market_value)
      setTransactions(txnR.data.data); setSnapshots(snapR.data.data)
      setIndexData(idxR.data.data ?? [])
      setStatsData(statsR.data.data ?? null)
    } catch { message.error('加载失败') } finally { setLoading(false) }
  }, [message])

  useEffect(() => { loadData() }, [loadData])

  const handleCodeChange = (val: string) => {
    const code = (val || '').trim()
    setOrderCode(code)
    const w = watchlist.find(x => x.code === code)
    setOrderName(w?.name || '')
  }

  const handleOrder = async () => {
    if (!orderCode) return message.warning('请输入或选择股票')
    setOrderLoading(true)
    try {
      await api.post('/trade/order', {
        code: orderCode, name: orderName || orderCode, direction: orderDirection,
        price: orderPrice || null, quantity: orderQty, strategy: orderStrategy || null,
      })
      message.success(`${orderDirection === 'buy' ? '买入' : '卖出'}成功`)
      setOrderCode(''); setOrderName(''); setOrderQty(100); setOrderPrice(null); setOrderStrategy(undefined); loadData()
    } catch (err: any) { message.error(err.response?.data?.detail || '下单失败') }
    finally { setOrderLoading(false) }
  }

  const handleQuickSell = (pos: any) => {
    setOrderCode(pos.code)
    setOrderName(pos.name)
    setOrderDirection('sell')
    setOrderPrice(pos.price ?? null)
    setOrderQty(pos.quantity)
    setActiveTab('order')
    message.info(`已填入 ${pos.name}（${pos.code}），确认价格数量后点击卖出`)
  }

  const openReset = () => {
    setResetCapital(account?.initial_capital || 100000)
    setResetOpen(true)
  }

  const handleReset = async () => {
    if (!resetCapital || resetCapital <= 0) return message.warning('请输入有效的初始资金')
    try {
      await api.post('/auto-trade/reset', { initial_capital: resetCapital })
      message.success('已重置')
      setResetOpen(false)
      loadData(); loadAutoTrade()
    } catch { message.error('重置失败') }
  }

  const loadAutoTrade = useCallback(async () => {
    try {
      const [itemsR, logsR] = await Promise.all([
        api.get('/auto-trade'), api.get('/auto-trade/logs'),
      ])
      setAutoItems(itemsR.data.data ?? [])
      setAutoLogs(logsR.data.data ?? [])
    } catch { /* 静默 */ }
  }, [])

  useEffect(() => { loadAutoTrade() }, [loadAutoTrade])

  const searchAutoStocks = async (kw: string) => {
    if (!kw) { setAutoOptions([]); return }
    try {
      const { data } = await api.get('/stock/search', { params: { keyword: kw } })
      setAutoOptions((data.data ?? []).map((s: any) => ({ value: s.code, label: `${s.name} ${s.code}`, name: s.name })))
    } catch { setAutoOptions([]) }
  }

  const handleAddAuto = async () => {
    if (!addAutoCode) return message.warning('请输入或选择股票')
    if (!addAutoStrategy) return message.warning('请选择策略')
    if (!addAutoPrice || addAutoPrice <= 0) return message.warning('请输入有效的买入价格')
    if (!addAutoQuantity || addAutoQuantity < 100 || addAutoQuantity % 100 !== 0) return message.warning('股数需为100的整数倍')
    setAddAutoLoading(true)
    try {
      await api.post('/auto-trade/item', {
        code: addAutoCode, name: addAutoName || addAutoCode,
        strategy_id: addAutoStrategy, price: addAutoPrice, quantity: addAutoQuantity,
      })
      message.success('已买入并加入自动交易')
      setAddAutoOpen(false)
      setAddAutoCode(''); setAddAutoName(''); setAddAutoPrice(null); setAddAutoQuantity(100); setAddAutoStrategy(undefined)
      loadAutoTrade(); loadData()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '买入失败')
    } finally { setAddAutoLoading(false) }
  }

  const openRemoveAuto = (item: any) => {
    setRemoveAutoItem(item)
    setRemoveAutoPrice(item.entry_price || null)
    setRemoveAutoOpen(true)
  }

  const handleRemoveAuto = async () => {
    if (!removeAutoItem) return
    if (!removeAutoPrice || removeAutoPrice <= 0) return message.warning('请输入有效的卖出价格')
    try {
      const { data } = await api.delete(`/auto-trade/item/${removeAutoItem.id}`, { params: { price: removeAutoPrice } })
      message.success(data.message || '已删除')
      setRemoveAutoOpen(false)
      setRemoveAutoItem(null); setRemoveAutoPrice(null)
      loadAutoTrade(); loadData()
    } catch (err: any) { message.error(err.response?.data?.detail || '删除失败') }
  }

  const handleToggleAuto = async (item: any, enabled: boolean) => {
    try {
      await api.put(`/auto-trade/item/${item.id}`, { enabled })
      loadAutoTrade()
    } catch (err: any) { message.error(err.response?.data?.detail || '操作失败') }
  }

  const handleAutoRun = async () => {
    setRunLoading(true)
    try {
      const { data } = await api.post('/auto-trade/run')
      const acted = (data.data ?? []).filter((r: any) => r.action !== 'skip' && r.action !== 'error')
      message.success(`调仓完成：${data.count ?? 0} 只标的，${acted.length} 笔操作`)
      loadAutoTrade(); loadData()
    } catch (err: any) { message.error(err.response?.data?.detail || '调仓失败') }
    finally { setRunLoading(false) }
  }

  const handleClearLogs = async () => {
    try {
      await api.delete('/auto-trade/logs')
      message.success('日志已清除')
      loadAutoTrade()
    } catch (err: any) { message.error(err.response?.data?.detail || '清除失败') }
  }

  const snapOption = (() => {
    const base = snapshots.length > 0 ? snapshots[0].total_asset : 0
    const dates = snapshots.map((s: any) => String(s.date))
    const assetLine = snapshots.map((s: any) =>
      base > 0 ? Number(((s.total_asset / base - 1) * 100).toFixed(2)) : 0)

    // 沪深300基准：按快照日期对齐
    const idxMap = new Map(indexData.map((d: any) => [String(d.date), d.close]))
    const firstIdx = indexData.find((d: any) => dates.includes(String(d.date)))
    const idxBase = firstIdx ? firstIdx.close : (indexData[0]?.close ?? 1)
    const indexLine = dates.map((date: string) => {
      const idx = idxMap.get(date)
      if (idx == null || idxBase == null) return null
      return Number(((idx / idxBase - 1) * 100).toFixed(2))
    })

    return {
      animation: false,
      tooltip: { trigger: 'axis', valueFormatter: (v: any) => (v == null ? '-' : `${v}%`) },
      legend: { data: ['账户收益率', '沪深300'], top: 0 },
      xAxis: { type: 'category', data: dates },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
      series: [
        { type: 'line', name: '账户收益率', data: assetLine,
          smooth: true, symbol: 'none', lineStyle: { color: '#1677ff', width: 2 },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: 'rgba(22,119,255,0.2)' }, { offset: 1, color: 'rgba(22,119,255,0.02)' }] } } },
        { type: 'line', name: '沪深300', data: indexLine,
          smooth: true, symbol: 'none', lineStyle: { color: '#faad14', width: 1.5, type: 'dashed' } },
      ],
    }
  })()

  const pieOption = {
    tooltip: { trigger: 'item' },
    series: [{ type: 'pie', radius: ['45%', '70%'],
      data: [
        { name: '可用资金', value: availableCash, itemStyle: { color: '#52c41a' } },
        ...positions.map((p: any) => ({ name: p.name, value: p.market_value })),
      ].filter(d => d.value > 0),
      label: { formatter: '{b}\n{d}%' } }],
  }

  const calendarOption = (() => {
    const cal = statsData?.calendar ?? []
    if (!cal.length) return null
    const values = cal.map((d: any) => Number(d.pnl))
    const maxAbs = Math.max(...values.map((v: number) => Math.abs(v)), 1)
    const years = cal.map((d: any) => Number(d.date.slice(0, 4)))
    const minYear = Math.min(...years)
    const maxYear = Math.max(...years)
    const range: any = minYear === maxYear ? String(minYear) : [`${minYear}-01-01`, `${maxYear}-12-31`]
    return {
      tooltip: {
        formatter: (p: any) => {
          const item = cal.find((d: any) => d.date === p.data[0])
          return `${p.data[0]}<br/>盈亏: ${item ? (item.pnl > 0 ? '+' : '') + item.pnl.toFixed(2) : '-'} 元 (${item ? item.pct.toFixed(2) : '0'}%)`
        },
      },
      visualMap: {
        min: -maxAbs, max: maxAbs,
        orient: 'horizontal', left: 'center', bottom: 0,
        inRange: { color: ['#3f8600', '#f5f5f5', '#cf1322'] },
      },
      calendar: {
        top: 40, left: 40, right: 20, bottom: 60,
        range,
        cellSize: ['auto', 14],
        splitLine: { show: false },
        itemStyle: { borderWidth: 2, borderColor: '#fff' },
        dayLabel: { nameMap: ['日', '一', '二', '三', '四', '五', '六'], firstDay: 1 },
        monthLabel: { nameMap: 'cn' },
        yearLabel: { show: false },
      },
      series: [{
        type: 'heatmap', coordinateSystem: 'calendar',
        data: cal.map((d: any) => [d.date, Number(d.pnl)]),
      }],
    }
  })()


  const posColumns = [
    { title: '代码', dataIndex: 'code', width: 100 },
    { title: '名称', dataIndex: 'name', width: 120 },
    { title: '策略', dataIndex: 'strategy_name', width: 130,
      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">-</Text> },
    { title: '持仓', dataIndex: 'quantity', width: 80, align: 'right' as const },
    { title: '成本', dataIndex: 'avg_cost', width: 90, align: 'right' as const, render: (v: any) => fmt(v) },
    { title: '现价', dataIndex: 'price', width: 90, align: 'right' as const, render: (v: any) => fmt(v) },
    { title: '市值', dataIndex: 'market_value', width: 110, align: 'right' as const, render: (v: any) => fmtMoney(v) },
    { title: '盈亏', dataIndex: 'pnl', width: 110, align: 'right' as const,
      render: (v: any, r: any) => <span style={{ color: pctClr(r.pnl) }}>{v != null ? (v > 0 ? '+' : '') + fmtMoney(v) : '-'}</span> },
    { title: '盈亏%', dataIndex: 'pnl_pct', width: 80, align: 'right' as const,
      render: (v: any) => <span style={{ color: pctClr(v) }}>{v != null ? `${v > 0 ? '+' : ''}${v.toFixed(2)}%` : '-'}</span> },
    { title: '操作', width: 70, render: (_: any, r: any) => (
      <Button size="small" type="primary" danger ghost onClick={() => handleQuickSell(r)}>卖出</Button>
    ) },
  ]

  const txnColumns = [
    { title: '时间', dataIndex: 'traded_at', width: 160, render: (v: string) => v?.replace('T', ' ') },
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '方向', dataIndex: 'direction', width: 60,
      render: (v: string) => <Tag color={v === 'buy' ? 'red' : 'green'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '策略', dataIndex: 'strategy_name', width: 110,
      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">-</Text> },
    { title: '价格', dataIndex: 'price', width: 80, align: 'right' as const, render: (v: any) => fmt(v) },
    { title: '数量', dataIndex: 'quantity', width: 70, align: 'right' as const },
    { title: '金额', dataIndex: 'amount', width: 110, align: 'right' as const, render: (v: any) => fmtMoney(v) },
    { title: '手续费', dataIndex: 'fee', width: 80, align: 'right' as const, render: (v: any) => v?.toFixed(2) },
  ]

  const autoColumns = [
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 110 },
    { title: '股数', dataIndex: 'quantity', width: 80, align: 'right' as const },
    { title: '策略', dataIndex: 'strategy_name', width: 120,
      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
    { title: '买入时间', dataIndex: 'started_at', width: 150, render: (v: string) => v?.replace('T', ' ') },
    { title: '买入价', dataIndex: 'entry_price', width: 80, align: 'right' as const, render: (v: any) => fmt(v) },
    { title: '启用', dataIndex: 'enabled', width: 70,
      render: (v: boolean, r: any) => <Switch size="small" checked={v} onChange={(c) => handleToggleAuto(r, c)} /> },
    { title: '操作', width: 90,
      render: (_: any, r: any) => (
        <Button size="small" danger onClick={() => openRemoveAuto(r)}>删除(卖出)</Button>
      ) },
  ]

  const autoLogColumns = [
    { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => v?.replace('T', ' ') },
    { title: '代码', dataIndex: 'code', width: 80 },
    { title: '名称', dataIndex: 'name', width: 90 },
    { title: '策略', dataIndex: 'strategy', width: 110, render: (v: string) => v || '-' },
    { title: '触发', dataIndex: 'trigger', width: 90, render: (v: string) => {
      const m: any = { manual_add: '加入', manual_remove: '删除', daily: '每日调仓', reset: '重置' }
      return m[v] || v
    } },
    { title: '信号', dataIndex: 'signal', width: 60, align: 'center' as const,
      render: (v: any) => v == null ? '-' : v === 1 ? <Tag color="red">买</Tag> : v === -1 ? <Tag color="green">卖</Tag> : <Text type="secondary">持</Text> },
    { title: '动作', dataIndex: 'action', width: 60,
      render: (v: string) => v === 'buy' ? <Tag color="red">买入</Tag> : v === 'sell' ? <Tag color="green">卖出</Tag> : <Text type="secondary">跳过</Text> },
    { title: '价格', dataIndex: 'price', width: 80, align: 'right' as const, render: (v: any) => fmt(v) },
    { title: '数量', dataIndex: 'quantity', width: 70, align: 'right' as const, render: (v: any) => v ?? '-' },
    { title: '结果', dataIndex: 'result', width: 200, render: (v: string) => v || '-' },
  ]

  const tabItems = [
    {
      key: 'order', label: '下单',
      children: (
        <Card>
          <Form layout="inline" style={{ flexWrap: 'wrap', gap: 8 }}>
            <Form.Item label="股票">
              <AutoComplete
                value={orderCode}
                options={watchlist.map((w: any) => ({ value: w.code, label: `${w.name} ${w.code}` }))}
                onChange={handleCodeChange}
                filterOption={(input, option) =>
                  (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
                }
                placeholder="选择自选股或输入代码"
                style={{ width: 180 }}
                allowClear
                notFoundContent={watchlist.length ? undefined : '暂无自选股，可手动输入代码'}
              />
            </Form.Item>
            <Form.Item label="方向">
              <Select value={orderDirection} onChange={setOrderDirection} style={{ width: 80 }}
                options={[{ value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]} />
            </Form.Item>
            <Form.Item label="价格"><InputNumber value={orderPrice} onChange={setOrderPrice} placeholder="市价" min={0} step={0.01} style={{ width: 100 }} /></Form.Item>
            <Form.Item label="数量(股)"><InputNumber value={orderQty} onChange={v => setOrderQty(v || 100)} min={100} step={100} style={{ width: 100 }} /></Form.Item>
            <Form.Item label="策略">
              <Select
                value={orderStrategy}
                onChange={setOrderStrategy}
                placeholder="选择策略(可选)"
                allowClear
                style={{ width: 160 }}
                options={strategies.map((s: any) => ({ value: s.name, label: s.name }))}
                notFoundContent={strategies.length ? undefined : '暂无策略，可先到策略页添加'}
              />
            </Form.Item>
            <Form.Item>
              <Button type="primary" icon={<ShoppingCartOutlined />} loading={orderLoading} onClick={handleOrder}>
                {orderDirection === 'buy' ? '买入' : '卖出'}
              </Button>
            </Form.Item>
          </Form>
        </Card>
      ),
    },
    {
      key: 'positions', label: '持仓',
      children: <Table dataSource={positions} columns={posColumns} rowKey="id" size="small" pagination={false}
        locale={{ emptyText: '暂无持仓' }} />,
    },
    {
      key: 'transactions', label: '成交记录',
      children: <Table dataSource={transactions} columns={txnColumns} rowKey="id" size="small"
        locale={{ emptyText: '暂无成交' }} />,
    },
    {
      key: 'autotrade', label: '自动交易',
      children: (
        <div>
          <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddAutoOpen(true)}>加入股票</Button>
            <Button icon={<PlayCircleOutlined />} loading={runLoading} onClick={handleAutoRun}>立即调仓一次</Button>
            <Text type="secondary" style={{ lineHeight: '32px' }}>系统每个交易日 14:50 自动按策略调仓；加入=买入、删除=卖出</Text>
          </div>
          <Table dataSource={autoItems} columns={autoColumns} rowKey="id" size="small" pagination={false}
            locale={{ emptyText: '暂无自动交易标的，点击「加入股票」开始' }} style={{ marginBottom: 16 }} />
          <Card size="small" title="执行日志" extra={<Button size="small" danger onClick={handleClearLogs}>清除日志</Button>}>
            <Table dataSource={autoLogs} columns={autoLogColumns} rowKey="id" size="small"
              pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无执行日志' }} />
          </Card>
        </div>
      ),
    },
    {
      key: 'charts', label: '图表',
      children: (
        <>
          {statsData?.stats && (
            <Card size="small" title="收益统计" style={{ marginBottom: 16 }}>
              <Descriptions size="small" column={{ xs: 2, sm: 3, md: 4 }} bordered>
                <Descriptions.Item label="累计收益">
                  <Text style={{ color: pctClr(statsData.stats.total_return) }}>{fmt(statsData.stats.total_return)}%</Text>
                </Descriptions.Item>
                <Descriptions.Item label="年化收益">
                  <Text style={{ color: pctClr(statsData.stats.annual_return) }}>{fmt(statsData.stats.annual_return)}%</Text>
                </Descriptions.Item>
                <Descriptions.Item label="今日收益">
                  <Text style={{ color: pctClr(statsData.stats.daily_return) }}>{fmt(statsData.stats.daily_return)}%</Text>
                </Descriptions.Item>
                <Descriptions.Item label="本周收益">
                  <Text style={{ color: pctClr(statsData.stats.weekly_return) }}>{fmt(statsData.stats.weekly_return)}%</Text>
                </Descriptions.Item>
                <Descriptions.Item label="本月收益">
                  <Text style={{ color: pctClr(statsData.stats.monthly_return) }}>{fmt(statsData.stats.monthly_return)}%</Text>
                </Descriptions.Item>
                <Descriptions.Item label="最大回撤">
                  <Text type="danger">{fmt(statsData.stats.max_drawdown)}%</Text>
                </Descriptions.Item>
                <Descriptions.Item label="夏普比率">
                  <Text style={{ color: pctClr(statsData.stats.sharpe) }}>{fmt(statsData.stats.sharpe)}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="胜率">
                  <Text>{fmt(statsData.stats.win_rate, 1)}%</Text>
                </Descriptions.Item>
              </Descriptions>
            </Card>
          )}
          {calendarOption && (
            <Card size="small" title="日盈亏日历" style={{ marginBottom: 16 }}>
              <ReactECharts option={calendarOption} style={{ height: 200 }} />
            </Card>
          )}
          {snapshots.length > 0
            ? <ReactECharts option={snapOption} style={{ height: 300 }} />
            : <Empty description="暂无资产数据，完成一笔交易后生成" />}
          <div style={{ height: 16 }} />
          {(positions.length > 0 || availableCash > 0)
            ? <ReactECharts option={pieOption} style={{ height: 300 }} />
            : null}
        </>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <Spin spinning={loading}>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}><Card><Statistic title="总资产" value={totalAsset} precision={2} prefix="¥" /></Card></Col>
          <Col span={6}><Card><Statistic title="可用资金" value={availableCash} precision={2} prefix="¥" valueStyle={{ color: '#52c41a' }} /></Card></Col>
          <Col span={6}><Card><Statistic title="持仓市值" value={marketValue} precision={2} prefix="¥" /></Card></Col>
          <Col span={6}><Card>
            <Statistic title="累计盈亏" value={totalPnl} precision={2} prefix="¥"
              valueStyle={{ color: pctClr(totalPnl) }}
              suffix={<span style={{ fontSize: 14 }}>（{totalPnlPct > 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%）</span>} />
          </Card></Col>
        </Row>

        <Card style={{ marginBottom: 16 }}
          extra={<Button size="small" danger onClick={openReset}>重置账户</Button>}>
          <Tabs items={tabItems} activeKey={activeTab} onChange={setActiveTab} />
        </Card>
      </Spin>

      <Modal
        title="重置账户"
        open={resetOpen}
        onOk={handleReset}
        onCancel={() => setResetOpen(false)}
        okText="确认重置"
        cancelText="取消"
      >
        <div style={{ marginBottom: 12, color: '#666' }}>
          设置初始资金后重置账户，将清空所有持仓和成交记录。
        </div>
        <Form layout="vertical">
          <Form.Item label="初始资金（元）">
            <InputNumber
              value={resetCapital}
              onChange={v => setResetCapital(v || 0)}
              min={1000}
              step={10000}
              style={{ width: '100%' }}
              prefix="¥"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="加入自动交易股票"
        open={addAutoOpen}
        onOk={handleAddAuto}
        onCancel={() => { setAddAutoOpen(false); setAddAutoCode(''); setAddAutoName('') }}
        okText="买入"
        cancelText="取消"
        confirmLoading={addAutoLoading}
      >
        <Form layout="vertical">
          <Form.Item label="股票" required>
            <AutoComplete
              value={addAutoCode}
              options={autoOptions}
              onSearch={searchAutoStocks}
              onChange={(v) => {
                setAddAutoCode(v)
                const o = autoOptions.find((x: any) => x.value === v)
                setAddAutoName(o?.name || '')
              }}
              placeholder="输入代码或名称搜索"
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item label="策略" required>
            <Select
              value={addAutoStrategy}
              onChange={setAddAutoStrategy}
              placeholder="选择策略"
              style={{ width: '100%' }}
              options={strategies.map((s: any) => ({ value: s.id, label: s.name }))}
              notFoundContent={strategies.length ? undefined : '暂无策略，请先到策略页添加'}
            />
          </Form.Item>
          <Form.Item label="买入价格（元）" required>
            <InputNumber value={addAutoPrice} onChange={v => setAddAutoPrice(v || null)} min={0.01} step={0.01} style={{ width: '100%' }} prefix="¥" />
          </Form.Item>
          <Form.Item label="买入股数" required>
            <InputNumber value={addAutoQuantity} onChange={v => setAddAutoQuantity(v || 100)} min={100} step={100} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`卖出 ${removeAutoItem?.name || ''}（${removeAutoItem?.code || ''}）`}
        open={removeAutoOpen}
        onOk={handleRemoveAuto}
        onCancel={() => { setRemoveAutoOpen(false); setRemoveAutoItem(null); setRemoveAutoPrice(null) }}
        okText="卖出"
        cancelText="取消"
      >
        <div style={{ marginBottom: 12, color: '#666' }}>
          将卖出该股票的全部可卖持仓（受 T+1 限制，当日买入部分次日才能卖出）。
        </div>
        <Form layout="vertical">
          <Form.Item label="卖出价格（元）" required>
            <InputNumber value={removeAutoPrice} onChange={v => setRemoveAutoPrice(v || null)} min={0.01} step={0.01} style={{ width: '100%' }} prefix="¥" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
