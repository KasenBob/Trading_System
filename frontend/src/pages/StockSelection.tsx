import { useState, useEffect } from 'react'
import { Card, Table, Button, Form, Tag, Typography, App, Spin, Empty, Progress, AutoComplete, Select } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { api } from '../services/api'

const { Text } = Typography

function fmt(v: any, d = 2) { return v == null ? '-' : Number(v).toFixed(d) }
function pctClr(v: any) { const n = Number(v); return isNaN(n) ? '#999' : n > 0 ? '#cf1322' : n < 0 ? '#3f8600' : '#999' }
function regimeColor(key: string) {
  const m: any = { uptrend: 'red', downtrend: 'green', pullback: 'orange', range: 'blue' }
  return m[key] || 'default'
}

// 行情选股的筛选规则列表
const SELECT_RULES = [
  '均线多头排列：MA5 > MA10 > MA20（硬前提，不满足直接跳过）',
  '通道1：站上MA5 + MACD翻红，或 通道2：突破过去20日最高收盘价 + 当日涨幅 < 9.5%',
  '收盘价 > MA60（生命线之上，确保不在熊市）',
]

export default function StockSelection() {
  const { message } = App.useApp()
  const [msLoading, setMsLoading] = useState(false)
  const [msProgress, setMsProgress] = useState(0)
  const [msResults, setMsResults] = useState<any[]>([])
  const [addedCodes, setAddedCodes] = useState<Set<string>>(new Set())

  // 加入自选
  const addToWatchlist = async (row: any) => {
    try {
      await api.post('/watchlist', {
        code: row.code, name: row.name,
        type: row.type === 'etf' ? 'etf' : 'stock',
      })
      setAddedCodes(prev => new Set(prev).add(row.code))
      message.success(`已加入自选：${row.name}`)
    } catch (err: any) {
      if (err.response?.status === 400) {
        setAddedCodes(prev => new Set(prev).add(row.code))
        message.warning('已在自选中')
      } else {
        message.error('加入自选失败')
      }
    }
  }

  // 加载最近一次选股结果（服务端持久化，刷新页面后仍展示）
  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get('/strategy/market-select/last')
        setMsResults(data.data ?? [])
      } catch { /* 静默 */ }
    })()
  }, [])

  // 运行行情选股（全市场 + 异步任务 + 进度轮询）
  const runMarketSelect = async () => {
    setMsLoading(true); setMsProgress(0)
    setMsResults([])
    try {
      const { data: startData } = await api.post('/strategy/market-select/start')
      const taskId = startData.task_id
      const poll = async (): Promise<any> => {
        const { data: progData } = await api.get(`/strategy/market-select/progress/${taskId}`)
        setMsProgress(progData.progress ?? 0)
        if (progData.status === 'done' || progData.status === 'error') {
          return progData
        }
        await new Promise(r => setTimeout(r, 800))
        return poll()
      }
      const finalStatus = await poll()
      if (finalStatus.status === 'error') {
        message.error('选股失败')
        return
      }
      const { data: resData } = await api.get(`/strategy/market-select/result/${taskId}`)
      const results = resData.data ?? []
      setMsResults(results)
      message.success(`行情选股完成，选出 ${results.length} 只`)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '行情选股失败')
    } finally {
      setMsLoading(false)
    }
  }

  // ── 个股分析板块 ──────────────────────
  const [searchKeyword, setSearchKeyword] = useState('')
  const [searchOptions, setSearchOptions] = useState<any[]>([])
  const [watchlist, setWatchlist] = useState<any[]>([])
  const [analysisStocks, setAnalysisStocks] = useState<any[]>([])  // {code, name, type}
  const [analysisRows, setAnalysisRows] = useState<any[]>([])      // 后端返回完整字段
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [regimeMap, setRegimeMap] = useState<Record<string, any>>({})

  // 加载自选股（供下拉选择）
  useEffect(() => {
    (async () => {
      try { const { data } = await api.get('/watchlist'); setWatchlist(data.data ?? []) } catch { /* 静默 */ }
    })()
  }, [])

  // 搜索股票
  const handleSearch = async (kw: string) => {
    setSearchKeyword(kw)
    if (!kw.trim()) { setSearchOptions([]); return }
    try {
      const { data } = await api.get('/stock/search', { params: { keyword: kw.trim() } })
      setSearchOptions(data.data ?? [])
    } catch { setSearchOptions([]) }
  }

  // 拉取分析列表的完整字段
  const fetchAnalysisData = async (stocks: any[]) => {
    if (!stocks.length) { setAnalysisRows([]); setRegimeMap({}); return }
    setAnalysisLoading(true)
    try {
      const codes = stocks.map((s: any) => s.code)
      const [rowsR, regimeR] = await Promise.all([
        api.post('/strategy/analyze-batch', { stocks }),
        api.post('/strategy/market-regime', { codes }),
      ])
      setAnalysisRows(rowsR.data.data ?? [])
      const map: Record<string, any> = {}
      for (const r of (regimeR.data.data ?? [])) map[r.code] = r
      setRegimeMap(map)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '获取股票数据失败')
    } finally {
      setAnalysisLoading(false)
    }
  }

  // 添加到分析列表（搜索或自选）
  const addStockToAnalysis = (item: any) => {
    setAnalysisStocks(prev => {
      if (prev.some(s => s.code === item.code)) {
        message.warning('已在分析列表中')
        return prev
      }
      const next = [...prev, { code: item.code, name: item.name, type: item.type || 'stock' }]
      fetchAnalysisData(next)
      return next
    })
  }

  // 从分析列表移除
  const removeStockFromAnalysis = (code: string) => {
    setAnalysisStocks(prev => {
      const next = prev.filter(s => s.code !== code)
      fetchAnalysisData(next)
      return next
    })
  }

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      {/* 个股分析 */}
      <Card title="个股分析">
        <Form layout="inline" style={{ marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
          <Form.Item label="搜索添加">
            <AutoComplete
              value={searchKeyword}
              options={searchOptions.map((s: any) => ({ value: s.code, label: `${s.name} ${s.code}` }))}
              onChange={setSearchKeyword}
              onSearch={handleSearch}
              onSelect={(val: string) => {
                const item = searchOptions.find((s: any) => s.code === val)
                if (item) addStockToAnalysis(item)
                setSearchKeyword(''); setSearchOptions([])
              }}
              placeholder="输入代码/名称搜索"
              style={{ width: 220 }}
            />
          </Form.Item>
          <Form.Item label="从自选添加">
            <Select
              placeholder="选择自选股"
              showSearch
              optionFilterProp="label"
              style={{ width: 200 }}
              options={watchlist.map((w: any) => ({ value: w.code, label: `${w.code} ${w.name}` }))}
              onSelect={(val: string) => {
                const item = watchlist.find((w: any) => w.code === val)
                if (item) addStockToAnalysis(item)
              }}
              notFoundContent={watchlist.length ? undefined : '暂无自选股，可先搜索添加'}
            />
          </Form.Item>
        </Form>

        <Spin spinning={analysisLoading} tip="获取数据中…">
          {analysisRows.length > 0 && (
            <>
            <Table dataSource={analysisRows} rowKey="code" size="small" pagination={false}
              scroll={{ x: 'max-content' }}
              columns={[
                { title: '代码', dataIndex: 'code', width: 90 },
                { title: '名称', dataIndex: 'name', width: 110 },
                { title: '类型', dataIndex: 'type', width: 60,
                  render: (v: string) => <Tag color={v === 'etf' ? 'blue' : 'default'}>{v === 'etf' ? 'ETF' : '股'}</Tag> },
                { title: '行情', dataIndex: 'code', width: 120,
                  render: (v: string) => {
                    const r = regimeMap[v]
                    return r ? <Tag color={regimeColor(r.regime_key)}>{r.regime}</Tag> : <Text type="secondary">-</Text>
                  } },
                { title: '行业', dataIndex: 'industry', width: 100,
                  render: (v: string) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">-</Text> },
                { title: 'PE', dataIndex: 'pe', width: 70, align: 'right' as const, render: (v: any) => v != null ? v.toFixed(1) : '-' },
                { title: 'EP(1/PE)', dataIndex: 'ep', width: 80, align: 'right' as const, render: (v: any) => v != null ? v.toFixed(2) : '-' },
                { title: 'ROE%', dataIndex: 'roe', width: 80, align: 'right' as const, render: (v: any) => v != null ? v.toFixed(2) : '-' },
                { title: '涨跌幅%', dataIndex: 'momentum', width: 90, align: 'right' as const,
                  render: (v: any) => <span style={{ color: pctClr(v) }}>{v != null ? `${v > 0 ? '+' : ''}${v.toFixed(2)}%` : '-'}</span> },
                { title: '总市值(亿)', dataIndex: 'market_cap', width: 100, align: 'right' as const, render: (v: any) => v != null ? v.toFixed(1) : '-' },
                { title: '移除', width: 60, render: (_: any, r: any) => (
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeStockFromAnalysis(r.code)} />
                ) },
              ]} />
            {analysisStocks.map(s => {
              const r = regimeMap[s.code]
              if (!r) return null
              return (
                <Card key={s.code} size="small" style={{ marginTop: 12 }}
                  title={<span>{s.name} ({s.code}) <Tag color={regimeColor(r.regime_key)}>{r.regime}</Tag></span>}>
                  <div style={{ marginBottom: 8 }}>{r.explanation}</div>
                  {r.signals?.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      {r.signals.map((sig: string, idx: number) => <Tag key={idx} color="blue">{sig}</Tag>)}
                    </div>
                  )}
                  {r.indicators && Object.keys(r.indicators).length > 0 && (
                    <div style={{ color: '#666', fontSize: 12, lineHeight: 1.9 }}>
                      <div>收盘 {r.indicators.close}　MA20 {r.indicators.ma20}</div>
                      <div>MACD：DIF {r.indicators.macd_dif}　DEA {r.indicators.macd_dea}　柱 {r.indicators.macd_hist}</div>
                      <div>KDJ：K {r.indicators.kdj_k}　D {r.indicators.kdj_d}　J {r.indicators.kdj_j}</div>
                      <div>布林带：上轨 {r.indicators.boll_upper}　中轨 {r.indicators.boll_mid}　下轨 {r.indicators.boll_lower}</div>
                    </div>
                  )}
                </Card>
              )
            })}
          </>
          )}
          {!analysisLoading && analysisRows.length === 0 && (
            <Empty description="搜索或从自选股添加股票，即可进行个股分析" />
          )}
        </Spin>
      </Card>

      <Card title="行情选股" style={{ marginTop: 16 }}
        extra={<Tag color="red" style={{ fontSize: 13 }}>共 {SELECT_RULES.length} 条筛选规则</Tag>}>
        <div style={{
          marginBottom: 16, padding: '10px 14px', background: '#fafafa',
          borderRadius: 6, fontSize: 13, lineHeight: 1.8,
        }}>
          <div style={{ marginBottom: 4 }}>
            <Text strong style={{ fontSize: 13 }}>选股条件（全部满足 → 进入候选池）：</Text>
          </div>
          {SELECT_RULES.map((rule, i) => (
            <div key={i} style={{ color: '#666' }}>
              {i + 1}. {rule}
            </div>
          ))}
        </div>
        <div style={{ marginBottom: 16 }}>
          <Button type="primary" loading={msLoading} onClick={runMarketSelect}>开始选股</Button>
        </div>

        <Spin spinning={msLoading} tip="全市场扫描中…">
          {msLoading && (
            <div style={{ padding: '20px 0' }}>
              <Progress percent={msProgress} status={msProgress >= 100 ? 'success' : 'active'} strokeColor="#1677ff" />
              <div style={{ textAlign: 'center', color: '#999', marginTop: 8 }}>
                正在扫描全市场股票…（{msProgress}%）
              </div>
            </div>
          )}
          {msResults.length > 0 && (
            <Table dataSource={msResults} rowKey="code" size="small" pagination={false}
              scroll={{ x: 1100 }}
              columns={[
                { title: '代码', dataIndex: 'code', width: 90 },
                { title: '名称', dataIndex: 'name', width: 110 },
                { title: '触发通道', dataIndex: 'channel', width: 170,
                  render: (v: string) => <Tag color="red">{v}</Tag> },
                { title: '当日涨幅%', dataIndex: 'gain_pct', width: 90, align: 'right' as const,
                  render: (v: any) => <span style={{ color: pctClr(v) }}>{v != null ? `${v > 0 ? '+' : ''}${v.toFixed(2)}%` : '-'}</span> },
                { title: '现价', dataIndex: 'close', width: 80, align: 'right' as const, render: (v: any) => fmt(v) },
                { title: 'MA5', dataIndex: 'ma5', width: 80, align: 'right' as const, render: (v: any) => fmt(v) },
                { title: 'MA10', dataIndex: 'ma10', width: 80, align: 'right' as const, render: (v: any) => fmt(v) },
                { title: 'MA20', dataIndex: 'ma20', width: 80, align: 'right' as const, render: (v: any) => fmt(v) },
                { title: 'MA60', dataIndex: 'ma60', width: 80, align: 'right' as const, render: (v: any) => fmt(v) },
                { title: '操作', width: 90, fixed: 'right' as const,
                  render: (_: any, r: any) => (
                    <Button size="small" type="primary" ghost
                      icon={<PlusOutlined />}
                      disabled={addedCodes.has(r.code)}
                      onClick={() => addToWatchlist(r)}>
                      {addedCodes.has(r.code) ? '已加入' : '加入自选'}
                    </Button>
                  ) },
              ]} />
          )}
          {!msLoading && msResults.length === 0 && (
            <Empty description="点击「开始选股」，扫描满足单边上升条件的股票" />
          )}
        </Spin>
      </Card>
    </div>
  )
}

