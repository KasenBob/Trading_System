import { useState, useEffect } from 'react'
import { Card, Table, Button, Form, Tag, Typography, App, Spin, Empty, Progress, AutoComplete, Select, Alert } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { api } from '../services/api'

const { Text } = Typography

function fmt(v: any, d = 2) { return v == null ? '-' : Number(v).toFixed(d) }
function pctClr(v: any) { const n = Number(v); return isNaN(n) ? '#999' : n > 0 ? '#cf1322' : n < 0 ? '#3f8600' : '#999' }
function regimeColor(key: string) {
  const m: any = { uptrend: 'red', downtrend: 'green', pullback: 'orange', range: 'blue' }
  return m[key] || 'default'
}

// 行情选股的筛选规则（三段式流程）
const SELECT_STAGES = [
  {
    title: '第一段 · 大环境过滤',
    rules: [
      '当日大盘跌幅 > 1% → 直接空仓，终止今日选股',
      '大盘均线空头排列(MA5<MA10<MA20) 且 MA20 下行 → 直接空仓，终止今日选股',
      '仅在【震荡企稳 / 温和上涨】状态下才继续下一步',
    ],
  },
  {
    title: '第二段 · 分轨制初筛（两轨互斥，不共享条件）',
    rules: [
      '顺势轨道（主力，100% 仓位）：MA60 连续 10 天上涨 + 收盘价 > MA60 + 偏离 MA20 ≤ 20% + 250 日位置 < 85%',
      '逆势轨道（试错，仓位 ≤ 30%）：MA60 走平或向下 + (股价 < MA60×0.8 或 RSI 历史低位)',
      '两轨共有：非 ST、上市天数 > 60 天、剔除创业板/科创板/北交所',
    ],
  },
  {
    title: '第三段 · 轨道内逐级匹配（能低吸就不追涨）',
    rules: [
      '顺势轨道：① 上升回调（低吸） → ② 单边上升（追涨）；回调不满足时才允许追涨',
      '　① 上升回调：上升趋势 + 近期缩量回调 + DIFF>0 + (J低位拐头 或 RSI 35~50) + 股价在 MA20 的 -5%~+3%；高于 MA20 超 5% 者须跌至布林下轨才可买入',
      '　② 单边上升：均线多头发散 + MACD 刚翻红 + (站上MA5 或 突破20日最高收盘价)，且当日涨幅 < 9.5%',
      '逆势轨道：③ 震荡盘整 → ④ 单边下跌',
      '　③ 震荡盘整：MA20>MA60 且均线走平 + (触及布林下轨 / RSI<30 / J<0且拐头) 至少满足两项',
      '　④ 单边下跌：RSI<20 + 最低价创20日新低 + MACD绿柱缩短 + 当日收阳，四条件缺一不可',
    ],
  },
  {
    title: '第四段 · 结果处理',
    rules: [
      '全局优先级：顺势轨道整体优先于逆势轨道',
      '若无任何标的命中 → 输出空仓建议并终止',
    ],
  },
]
const SELECT_RULE_COUNT = SELECT_STAGES.reduce((n, s) => n + s.rules.length, 0)

// 四大策略标签配色
const STRATEGY_COLORS: Record<string, string> = {
  pullback: 'red', uptrend: 'volcano', oscillation: 'blue', downtrend: 'green',
}
// 轨道配色
const TRACK_COLORS: Record<string, string> = { trend: 'gold', counter: 'purple' }

export default function StockSelection() {
  const { message } = App.useApp()
  const [msLoading, setMsLoading] = useState(false)
  const [msProgress, setMsProgress] = useState(0)
  const [msResults, setMsResults] = useState<any[]>([])
  const [msStats, setMsStats] = useState<any>({})
  const [msAction, setMsAction] = useState<string>('select')
  const [msMessage, setMsMessage] = useState<string>('')
  const [msMarket, setMsMarket] = useState<any>({})
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
        setMsStats(data.stats ?? {})
        setMsAction(data.action ?? 'select')
        setMsMessage(data.message ?? '')
        setMsMarket(data.market ?? {})
      } catch { /* 静默 */ }
    })()
  }, [])

  // 运行行情选股（全市场 + 异步任务 + 进度轮询）
  const runMarketSelect = async () => {
    setMsLoading(true); setMsProgress(0)
    setMsResults([])
    setMsStats({})
    setMsAction('select')
    setMsMessage('')
    setMsMarket({})
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
        // 进度接口不带 error 详情，单独取一次结果接口拿原因与统计
        const { data: errData } = await api.get(`/strategy/market-select/result/${taskId}`)
        setMsStats(errData.stats ?? {})
        message.error(errData.error || '选股失败')
        return
      }
      const { data: resData } = await api.get(`/strategy/market-select/result/${taskId}`)
      const results = resData.data ?? []
      setMsResults(results)
      const st = resData.stats ?? {}
      setMsStats(st)
      setMsAction(resData.action ?? 'select')
      setMsMessage(resData.message ?? '')
      setMsMarket(resData.market ?? {})
      if (resData.action === 'empty') {
        message.warning(resData.message || '今日建议空仓')
      } else if (st.fetch_failed > 0) {
        message.warning(`选股完成，选出 ${results.length} 只（${st.fetch_failed} 只取数失败未参与判定）`)
      } else {
        message.success(`行情选股完成，选出 ${results.length} 只`)
      }
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
        extra={<Tag color="red" style={{ fontSize: 13 }}>共 {SELECT_RULE_COUNT} 条筛选规则</Tag>}>
        <div style={{
          marginBottom: 16, padding: '10px 14px', background: '#fafafa',
          borderRadius: 6, fontSize: 13, lineHeight: 1.8,
        }}>
          {SELECT_STAGES.map((stage, si) => (
            <div key={si} style={{ marginBottom: si < SELECT_STAGES.length - 1 ? 8 : 0 }}>
              <Text strong style={{ fontSize: 13 }}>{stage.title}</Text>
              {stage.rules.map((rule, ri) => (
                <div key={ri} style={{ color: '#666', paddingLeft: 12 }}>· {rule}</div>
              ))}
            </div>
          ))}
        </div>
        <div style={{ marginBottom: 16 }}>
          <Button type="primary" loading={msLoading} onClick={runMarketSelect}>开始选股</Button>
        </div>

        {msMarket?.label && (
          <Alert
            type={msMarket.blocked ? 'error' : msMarket.available === false ? 'warning' : 'info'}
            showIcon
            style={{ marginBottom: 16 }}
            message={`大盘环境：${msMarket.label}${msMarket.change_pct != null ? `（${msMarket.change_pct > 0 ? '+' : ''}${msMarket.change_pct}%）` : ''}`}
            description={<span style={{ fontSize: 12 }}>{msMarket.reason}</span>}
          />
        )}

        {msAction === 'empty' && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="今日建议空仓"
            description={<span style={{ fontSize: 12 }}>{msMessage || '无符合条件的标的，建议空仓等待。'}</span>}
          />
        )}

        {msStats?.candidates > 0 && (
          <Alert
            type={(msStats.fetch_failed ?? 0) > 0 ? 'warning' : 'success'}
            showIcon
            style={{ marginBottom: 16 }}
            message={`扫描 ${msStats.candidates} 只候选 → 命中 ${msStats.matched} 只（基准交易日 ${msStats.reference_date || '-'}）`}
            description={
              <span style={{ fontSize: 12 }}>
                剔除板块 {msStats.skipped_board ?? 0} · 剔除 ST {msStats.skipped_st ?? 0} ·
                停牌/无成交 {msStats.stale ?? 0} · 取数失败 {msStats.fetch_failed ?? 0}
                {(msStats.fallback_sina ?? 0) > 0 && ` · ${msStats.fallback_sina} 只用的是不复权兜底数据`}
                {msStats.by_track && (
                  `　轨道：顺势 ${msStats.by_track.trend ?? 0} / 逆势 ${msStats.by_track.counter ?? 0}`
                )}
                {msStats.by_strategy && (
                  `　策略：回调 ${msStats.by_strategy.pullback ?? 0} / 单边上升 ${msStats.by_strategy.uptrend ?? 0}`
                  + ` / 震荡 ${msStats.by_strategy.oscillation ?? 0} / 单边下跌 ${msStats.by_strategy.downtrend ?? 0}`
                )}
                {(msStats.fetch_failed ?? 0) > 0 && '　⚠ 取数失败的股票未参与判定，结果可能不完整'}
              </span>
            }
          />
        )}

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
              scroll={{ x: 1400 }}
              columns={[
                { title: '代码', dataIndex: 'code', width: 90 },
                { title: '名称', dataIndex: 'name', width: 110 },
                { title: '轨道', dataIndex: 'track_label', width: 90,
                  render: (v: string, r: any) => <Tag color={TRACK_COLORS[r.track] || 'default'}>{v}</Tag> },
                { title: '策略', dataIndex: 'strategy_label', width: 120,
                  render: (v: string, r: any) => <Tag color={STRATEGY_COLORS[r.strategy] || 'red'}>{v}</Tag> },
                { title: '触发条件', dataIndex: 'reason', width: 280, ellipsis: true },
                { title: '仓位', dataIndex: 'position_size', width: 70, align: 'right' as const,
                  render: (v: any) => `${Math.round((Number(v) || 1) * 100)}%` },
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

