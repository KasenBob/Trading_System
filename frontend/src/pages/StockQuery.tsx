import { useState, useCallback, useRef, useEffect } from 'react'
import {
  Input, Card, Descriptions, Tabs, Spin, Empty, Typography, Tag, App, AutoComplete, Segmented, Button, Switch, Space, Table,
} from 'antd'
import { SearchOutlined, RiseOutlined, FallOutlined, MinusOutlined, StarOutlined, ReloadOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import type { KlineItem, MinuteItem, FundFlowItem, FinancialItem } from '../services/api'
import { api, searchStocks, getStockDetail, getKline, getMinuteData, getFundFlow, getStockFinancial } from '../services/api'

const { Title, Text } = Typography

function pctColor(v: number | null | undefined): string {
  if (v == null) return '#999'
  if (v > 0) return '#cf1322'; if (v < 0) return '#3f8600'; return '#999'
}
function pctIcon(v: number | null | undefined) {
  if (v == null) return <MinusOutlined />
  if (v > 0) return <RiseOutlined />; if (v < 0) return <FallOutlined />; return <MinusOutlined />
}
function fmt(v: number | null | undefined, d = 2) { return v == null ? '-' : v.toFixed(d) }
function fmtVol(v: number | null | undefined): string {
  if (v == null) return '-'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

// ─── K线图 ──────────────────────────────────

function makeKlineOption(data: KlineItem[], flowData: FundFlowItem[], volMode: string) {
  const dates = data.map(d => d.date)
  const ohlc = data.map(d => [d.open, d.close, d.low, d.high])
  const volumes = data.map(d => d.volume)
  const closes = data.map(d => d.close)
  const flowMap: Record<string, number> = {}
  flowData.forEach(f => { flowMap[f.date] = f.retail_net_inflow })
  const retailLine = data.map(d => flowMap[d.date] ?? null)

  // 计算均线（简单移动平均）
  const calcMA = (period: number): (number | null)[] =>
    closes.map((_, i) => {
      if (i < period - 1) return null
      let sum = 0
      for (let j = i - period + 1; j <= i; j++) sum += closes[j]
      return Number((sum / period).toFixed(3))
    })
  const ma5 = calcMA(5)
  const ma20 = calcMA(20)
  const ma60 = calcMA(60)

  const volSeries: any = volMode === 'retail'
    ? {
        type: 'line', name: '散户净流入', data: retailLine, xAxisIndex: 1, yAxisIndex: 1,
        lineStyle: { color: '#faad14', width: 1.5 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(250,173,20,0.3)' }, { offset: 1, color: 'rgba(250,173,20,0.02)' }] } },
      }
    : {
        type: 'bar', name: '成交量', data: volumes, xAxisIndex: 1, yAxisIndex: 1,
        itemStyle: { color: (p: any) => { const d = data[p.dataIndex]; return d.close >= d.open ? '#cf1322' : '#3f8600' } },
      }

  return {
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    legend: {
      data: ['MA5', 'MA20', 'MA60'],
      top: 0,
      left: 'center',
      textStyle: { fontSize: 12, color: '#666' },
      itemWidth: 18,
      itemHeight: 8,
    },
    grid: [
      { left: 70, right: 20, top: 32, height: '52%' },
      { left: 70, right: 20, top: '75%', height: '15%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 1 },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true },
      { type: 'value', gridIndex: 1, scale: volMode === 'retail' },
    ],
    series: [
      { type: 'candlestick', name: 'K线', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: '#cf1322', color0: '#3f8600', borderColor: '#cf1322', borderColor0: '#3f8600' } },
      { type: 'line', name: 'MA5', data: ma5, xAxisIndex: 0, yAxisIndex: 0,
        symbol: 'none', lineStyle: { color: '#faad14', width: 1 } },
      { type: 'line', name: 'MA20', data: ma20, xAxisIndex: 0, yAxisIndex: 0,
        symbol: 'none', lineStyle: { color: '#722ed1', width: 1 } },
      { type: 'line', name: 'MA60', data: ma60, xAxisIndex: 0, yAxisIndex: 0,
        symbol: 'none', lineStyle: { color: '#1677ff', width: 1 } },
      volSeries,
    ],
  }
}

// ─── 分时图 ──────────────────────────────────

function makeMinuteOption(minData: MinuteItem[], preClose: number | null, volMode: string) {
  const times = minData.map(d => d.time)
  const prices = minData.map(d => d.price)
  const vols = minData.map(d => d.volume)
  const cumVols = minData.map(d => d.cum_volume)
  const baseline = preClose ?? (minData[0]?.price ?? 0)

  const volSeries: any = volMode === 'retail'
    ? {
        type: 'line', name: '累计成交量', data: cumVols, xAxisIndex: 1, yAxisIndex: 1,
        smooth: true, symbol: 'none',
        lineStyle: { color: '#faad14', width: 1.5 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(250,173,20,0.25)' }, { offset: 1, color: 'rgba(250,173,20,0.02)' }] } },
      }
    : {
        type: 'bar', name: '成交量', data: vols, xAxisIndex: 1, yAxisIndex: 1,
        itemStyle: { color: (p: any) => {
          if (p.dataIndex === 0) return '#999'
          return minData[p.dataIndex].price >= minData[p.dataIndex - 1].price ? '#cf1322' : '#3f8600'
        } },
      }

  return {
    animation: false,
    tooltip: { trigger: 'axis' },
    grid: [
      { left: 60, right: 60, top: 20, height: '55%' },
      { left: 60, right: 60, top: '75%', height: '15%' },
    ],
    xAxis: [
      { type: 'category', data: times, gridIndex: 0, axisLabel: { interval: 29 }, boundaryGap: false },
      { type: 'category', data: times, gridIndex: 1, axisLabel: { interval: 29 }, boundaryGap: false },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true, axisLine: { lineStyle: { color: '#999' } }, splitLine: { show: false } },
      { type: 'value', gridIndex: 1, axisLabel: { show: volMode !== 'retail' }, splitLine: { show: false } },
    ],
    series: [
      {
        type: 'line', name: '价格', data: prices, smooth: false, symbol: 'none',
        lineStyle: { color: '#1677ff', width: 1 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(22,119,255,0.15)' }, { offset: 1, color: 'rgba(22,119,255,0.02)' }] } },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#999', type: 'dashed', width: 1 },
          data: [{ yAxis: baseline, label: { formatter: `昨收 ${baseline.toFixed(2)}`, position: 'end' } }] },
        xAxisIndex: 0, yAxisIndex: 0,
      },
      volSeries,
    ],
  }
}

// ─── 组件 ─────────────────────────────────────

type ChartTab = 'minute' | '60min' | 'daily' | 'weekly' | 'monthly'

export default function StockQuery() {
  const { message } = App.useApp()
  const [searchParams] = useSearchParams()

  const [keyword, setKeyword] = useState('')
  const [options, setOptions] = useState<{ value: string; label: React.ReactNode }[]>([])
  const [searching, setSearching] = useState(false)
  const searchTimer = useRef<ReturnType<typeof setTimeout>>(0)

  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [chartTab, setChartTab] = useState<ChartTab>('daily')
  const [chartLoading, setChartLoading] = useState(false)

  const [klineData, setKlineData] = useState<KlineItem[]>([])
  const [minuteData, setMinuteData] = useState<MinuteItem[]>([])
  const [fundFlowData, setFundFlowData] = useState<FundFlowItem[]>([])
  const [financialData, setFinancialData] = useState<FinancialItem[]>([])
  const [volMode, setVolMode] = useState<string>('volume')
  const [watchlisted, setWatchlisted] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastUpdate, setLastUpdate] = useState<string>('')
  const [stablePreClose, setStablePreClose] = useState<number | null>(null)

  // 交易时间判断（周一至周五 9:30-11:30, 13:00-15:00）
  const isTradingTime = () => {
    const now = new Date()
    const day = now.getDay()
    if (day === 0 || day === 6) return false
    const minutes = now.getHours() * 60 + now.getMinutes()
    return (minutes >= 570 && minutes <= 690) || (minutes >= 780 && minutes <= 900)
  }

  // 刷新分时数据
  const refreshMinute = useCallback(async (code: string, silent = true) => {
    try {
      const d = await getMinuteData(code)
      setMinuteData(d)
      setLastUpdate(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
    } catch {
      if (!silent) message.warning('分时数据刷新失败')
    }
  }, [message])

  // 刷新实时行情（价格、最高、最低、成交量等）
  const refreshQuote = useCallback(async (code: string, silent = true) => {
    try {
      const { data } = await api.get('/market/realtime', { params: { codes: code } })
      const quotes = data.data ?? []
      if (quotes.length) {
        setDetail((prev: any) => prev ? { ...prev, quote: quotes[0] } : prev)
        setLastUpdate(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
      }
    } catch {
      if (!silent) message.warning('行情刷新失败')
    }
  }, [message])

  // 交易时间内自动刷新实时行情（不分 Tab，只要有股票详情）
  useEffect(() => {
    if (!detail || !autoRefresh) return
    if (!isTradingTime()) return
    refreshQuote(detail.code)
    const timer = setInterval(() => {
      refreshQuote(detail.code)
    }, 5000)
    return () => clearInterval(timer)
  }, [detail, autoRefresh, refreshQuote])

  // 分时 Tab 激活时，自动刷新（仅交易时间）
  useEffect(() => {
    if (chartTab !== 'minute' || !detail || !autoRefresh) return
    if (!isTradingTime()) return
    refreshMinute(detail.code)
    const timer = setInterval(() => {
      refreshMinute(detail.code)
    }, 5000)
    return () => clearInterval(timer)
  }, [chartTab, detail, autoRefresh, refreshMinute])

  // 从 URL 参数加载股票
  useEffect(() => {
    const code = searchParams.get('code')
    if (code) handleSelect(code)
  }, [searchParams])



  const handleSearch = useCallback((value: string) => {
    setKeyword(value)
    if (!value.trim()) { setOptions([]); return }
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(async () => {
      setSearching(true)
      try {
        const results = await searchStocks(value.trim())
        setOptions(results.map(r => ({
          value: r.code, label: <span>
            <Tag color={r.type === 'etf' ? 'blue' : 'default'} style={{ fontSize: 11, marginRight: 4 }}>{r.type === 'etf' ? 'ETF' : '股'}</Tag>
            <Text strong>{r.code}</Text>
            <Text style={{ marginLeft: 8, color: '#666' }}>{r.name}</Text>
          </span>,
        })))
      } catch { message.error('搜索失败，请检查网络后重试'); setOptions([])
      } finally { setSearching(false) }
    }, 350)
  }, [message])

  const handleSelect = useCallback(async (code: string) => {
    setLoading(true); setDetail(null); setWatchlisted(false)
    setKlineData([]); setMinuteData([]); setFundFlowData([]); setFinancialData([]); setChartTab('daily')
    try {
      const d = await getStockDetail(code); setDetail(d)
      setStablePreClose(d.quote?.pre_close ?? null)
      message.success(`已加载 ${d.quote?.name || code}`)
      // 检查是否已在自选
      try {
        const { data: wl } = await api.get('/watchlist')
        setWatchlisted((wl.data ?? []).some((i: any) => i.code === code))
      } catch { /* 静默 */ }
      setChartLoading(true)
      const startDate = new Date(Date.now() - 730 * 86400000).toISOString().slice(0, 10).replace(/-/g, '')
      const [kr, mr, fr, fin] = await Promise.allSettled([
        getKline(code, 'daily', startDate), getMinuteData(code), getFundFlow(code, 60), getStockFinancial(code),
      ])
      if (kr.status === 'fulfilled') setKlineData(kr.value)
      else message.warning('K线数据获取失败')
      if (mr.status === 'fulfilled') setMinuteData(mr.value)
      if (fr.status === 'fulfilled') setFundFlowData(fr.value)
      if (fin.status === 'fulfilled') setFinancialData(fin.value)
    } catch { message.error('获取详情失败')
    } finally { setLoading(false); setChartLoading(false) }
  }, [message])

  const handleChartTab = useCallback(async (key: string) => {
    const tab = key as ChartTab; setChartTab(tab)
    if (!detail || tab === 'minute') return
    setChartLoading(true)
    try {
      const startDate = new Date(Date.now() - 730 * 86400000).toISOString().slice(0, 10).replace(/-/g, '')
      setKlineData(await getKline(detail.code, tab, tab === 'daily' ? startDate : undefined))
    }
    catch { message.warning('K线数据获取失败') }
    finally { setChartLoading(false) }
  }, [detail, message])

  const q = detail?.quote; const cp = q?.change_pct ?? null


  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <Card style={{ marginBottom: 16 }}>
        <AutoComplete value={keyword} options={options} onSearch={handleSearch}
          onSelect={(val) => { handleSelect(val); setKeyword('') }} style={{ width: '100%' }}
          notFoundContent={searching ? <Spin size="small" style={{ padding: 8 }} /> : keyword ? <Empty description="未找到匹配股票" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}>
          <Input size="large" placeholder="输入股票代码 / 名称 / 拼音搜索…" prefix={<SearchOutlined />}
            suffix={searching ? <Spin size="small" /> : null} allowClear onClear={() => setOptions([])} />
        </AutoComplete>
      </Card>

      {loading && <Card><div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" /><div style={{ marginTop: 16, color: '#999' }}>正在加载股票数据…</div>
      </div></Card>}

      {!loading && !detail && <Card><Empty description="搜索股票代码或名称查看详情"
        image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 60 }} /></Card>}

      {!loading && detail && (<>
        <Card style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
            <Title level={3} style={{ margin: 0 }}>{q?.name || detail.code}</Title>
            <Text type="secondary" style={{ fontSize: 16 }}>{detail.code}</Text>
            {q?.price != null && (<>
              <Text style={{ fontSize: 28, fontWeight: 700, color: pctColor(cp) }}>{q.price.toFixed(2)}</Text>
              <Tag color={cp != null && cp > 0 ? 'red' : cp != null && cp < 0 ? 'green' : 'default'}
                style={{ fontSize: 16, padding: '2px 10px' }} icon={pctIcon(cp)}>
                {cp != null ? `${cp > 0 ? '+' : ''}${cp.toFixed(2)}%` : '-'}
              </Tag>
            </>)}
            <Button
              type={watchlisted ? 'default' : 'dashed'}
              size="small"
              icon={watchlisted ? <span style={{ color: '#faad14' }}>★</span> : <StarOutlined />}
              disabled={watchlisted}
              onClick={async () => {
                if (!detail) return
                try {
                  await api.post('/watchlist', {
                    code: detail.code, name: q?.name || detail.code,
                    type: detail.code.startsWith('51') || detail.code.startsWith('15') ? 'etf' : 'stock',
                  })
                  setWatchlisted(true)
                  message.success('已加入自选')
                } catch (err: any) {
                  message.warning(err.response?.data?.detail || '添加失败')
                }
              }}>
              {watchlisted ? '已加入自选' : '加入自选'}
            </Button>
          </div>
          <Descriptions column={4} size="small" bordered>
            <Descriptions.Item label="开盘">{fmt(q?.open)}</Descriptions.Item>
            <Descriptions.Item label="最高">{fmt(q?.high)}</Descriptions.Item>
            <Descriptions.Item label="最低">{fmt(q?.low)}</Descriptions.Item>
            <Descriptions.Item label="昨收">{fmt(q?.pre_close)}</Descriptions.Item>
            <Descriptions.Item label="成交量">{fmtVol(q?.volume)}</Descriptions.Item>
            <Descriptions.Item label="成交额">{fmtVol(q?.amount)}</Descriptions.Item>
          </Descriptions>
        </Card>

        <Card title={
          <Tabs activeKey={chartTab} onChange={(k) => handleChartTab(k)}
            items={[
              { key: 'minute', label: '分时' },
              { key: '60min', label: '60分钟' },
              { key: 'daily', label: '日K' },
              { key: 'weekly', label: '周K' },
              { key: 'monthly', label: '月K' },
            ]} style={{ marginBottom: -16 }} />
        } extra={
          <Space size="middle">
            <Space size={4}>
              <Text type="secondary" style={{ fontSize: 12 }}>自动刷新</Text>
              <Switch size="small" checked={autoRefresh} onChange={setAutoRefresh} />
              {lastUpdate && <Text type="secondary" style={{ fontSize: 12 }}>{lastUpdate}</Text>}
              <Button size="small" type="text" icon={<ReloadOutlined />}
                onClick={() => {
                  refreshQuote(detail.code, false)
                  if (chartTab === 'minute') refreshMinute(detail.code, false)
                  else handleChartTab(chartTab)
                }} />
            </Space>
            <Segmented size="small" value={volMode} onChange={(v) => setVolMode(v as string)}
              options={[{ value: 'volume', label: '成交量' }, { value: 'retail', label: '散户线' }]} />
          </Space>
        }>
          <Spin spinning={chartLoading} tip="加载中…">
            {chartTab === 'minute'
              ? (minuteData.length > 0
                  ? <ReactECharts option={makeMinuteOption(minuteData, stablePreClose, volMode)} style={{ height: 500 }} notMerge />
                  : <Empty description="暂无分时数据（非交易时间）" style={{ padding: 40 }} />)
              : (klineData.length > 0
                  ? <ReactECharts option={makeKlineOption(klineData, fundFlowData, volMode)} style={{ height: 500 }} notMerge />
                  : <Empty description="暂无K线数据" style={{ padding: 40 }} />)}
          </Spin>
        </Card>

        {/* 财务数据 */}
        {financialData.length > 0 && (
          <Card title="财务指标" style={{ marginTop: 16 }}>
            <Table
              dataSource={financialData}
              rowKey="date"
              size="small"
              pagination={false}
              scroll={{ x: 800 }}
              columns={[
                { title: '报告期', dataIndex: 'date', width: 100, fixed: 'left' as const },
                { title: '净资产收益率(ROE)', dataIndex: 'roe', width: 140, align: 'right' as const,
                  render: (v: any) => v != null ? <Text style={{ color: pctColor(v) }}>{v.toFixed(2)}%</Text> : '-' },
                { title: '净利润增长率', dataIndex: 'profit_growth', width: 110, align: 'right' as const,
                  render: (v: any) => v != null ? <span style={{ color: pctColor(v) }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span> : '-' },
                { title: '营收增长率', dataIndex: 'revenue_growth', width: 110, align: 'right' as const,
                  render: (v: any) => v != null ? <span style={{ color: pctColor(v) }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span> : '-' },
                { title: '每股收益(EPS)', dataIndex: 'eps', width: 110, align: 'right' as const,
                  render: (v: any) => v != null ? v.toFixed(4) : '-' },
                { title: '每股净资产', dataIndex: 'bps', width: 100, align: 'right' as const,
                  render: (v: any) => v != null ? v.toFixed(2) : '-' },
                { title: '资产负债率', dataIndex: 'debt_ratio', width: 100, align: 'right' as const,
                  render: (v: any) => v != null ? v.toFixed(2) + '%' : '-' },
              ]}
            />
          </Card>
        )}
      </>)}
    </div>
  )
}
