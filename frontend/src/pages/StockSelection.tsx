import { useState, useEffect } from 'react'
import { Card, Table, Button, Form, InputNumber, Tag, Typography, App, Spin, Empty, Progress, AutoComplete, Select } from 'antd'
import { PlusOutlined, RobotOutlined, DeleteOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../services/api'

const { Text } = Typography

function fmt(v: any, d = 2) { return v == null ? '-' : Number(v).toFixed(d) }
function pctClr(v: any) { const n = Number(v); return isNaN(n) ? '#999' : n > 0 ? '#cf1322' : n < 0 ? '#3f8600' : '#999' }
function regimeColor(key: string) {
  const m: any = { uptrend: 'red', downtrend: 'green', pullback: 'orange', range: 'blue' }
  return m[key] || 'default'
}

// 多因子选股的筛选规则列表
const FILTER_RULES = [
  'ROE > 10%（硬性门槛）',
  'EP > 0.03（硬性门槛）',
  'ROE ≤ 35%（剔除 ROE>35% 的股票）',
  '20日涨幅 ≤ 20%（剔除短期暴涨）',
  '一票否决：任一因子得分不得在后 20%',
  'ROE 按名次打分（从高到低，最高1分，最低0分）',
]

export default function StockSelection() {
  const { message } = App.useApp()
  const [mfWeights, setMfWeights] = useState({ ep: 0.35, roe: 0.3, momentum: 0.1, market_cap: 0.25 })
  const [mfTopN, setMfTopN] = useState(10)
  const [mfLoading, setMfLoading] = useState(false)
  const [mfProgress, setMfProgress] = useState(0)
  const [mfResults, setMfResults] = useState<any[]>(() => {
    try {
      const saved = localStorage.getItem('multifactor_results')
      return saved ? JSON.parse(saved) : []
    } catch { return [] }
  })
  const [addedCodes, setAddedCodes] = useState<Set<string>>(new Set())
  const [mfUsePrecise, setMfUsePrecise] = useState<boolean | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiResult, setAiResult] = useState('')

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

  // AI 分析（DeepSeek）
  const doAiAnalysis = async (stocks: any[]) => {
    setAiLoading(true)
    setAiResult('')
    try {
      const { data } = await api.post('/strategy/ai-analysis', { stocks })
      setAiResult(data.data)
    } catch (err: any) {
      setAiResult('')
      message.error(err.response?.data?.detail || 'AI 分析失败')
    } finally {
      setAiLoading(false)
    }
  }

  // 结果持久化：切换页面再回来时能恢复
  useEffect(() => {
    try { localStorage.setItem('multifactor_results', JSON.stringify(mfResults)) } catch { /* 静默 */ }
  }, [mfResults])

  // 运行多因子选股（全市场 + 异步任务 + 进度轮询）
  const runMultifactor = async () => {
    setMfLoading(true); setMfProgress(0)
    setMfResults([]); setAiResult('')   // 清空旧结果，避免显示过时数据
    try {
      // 启动任务
      const { data: startData } = await api.post('/strategy/multifactor/full/start', {
        weights: mfWeights, top_n: mfTopN,
      })
      const taskId = startData.task_id
      // 轮询进度
      const poll = async (): Promise<any> => {
        const { data: progData } = await api.get(`/strategy/multifactor/full/progress/${taskId}`)
        setMfProgress(progData.progress ?? 0)
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
      // 获取结果
      const { data: resData } = await api.get(`/strategy/multifactor/full/result/${taskId}`)
      const results = resData.data ?? []
      setMfResults(results)
      setMfUsePrecise(resData.use_precise_finance ?? false)
      message.success(`全市场选股完成，选出 ${results.length} 只`)
      // 选股完成后自动进行 AI 分析
      if (results.length > 0) doAiAnalysis(results)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '多因子选股失败')
    } finally {
      setMfLoading(false)
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

      <Card title="多因子选股" style={{ marginTop: 16 }}
        extra={<Tag color="blue" style={{ fontSize: 13 }}>共 {FILTER_RULES.length} 条筛选规则</Tag>}>
        <div style={{
          marginBottom: 16, padding: '10px 14px', background: '#fafafa',
          borderRadius: 6, fontSize: 13, lineHeight: 1.8,
        }}>
          <div style={{ marginBottom: 4 }}>
            <Text strong style={{ fontSize: 13 }}>筛选规则：</Text>
            {mfUsePrecise != null && (
              <Tag color={mfUsePrecise ? 'green' : 'orange'} style={{ marginLeft: 8 }}>
                {mfUsePrecise ? '财务数据：东财精确值' : '财务数据：近似值(PB/PE)'}
              </Tag>
            )}
          </div>
          {FILTER_RULES.map((rule, i) => (
            <div key={i} style={{ color: '#666' }}>
              {i + 1}. {rule}
            </div>
          ))}
        </div>
        <Form layout="inline" style={{ marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
          <Form.Item label="EP权重(市盈率倒数)">
            <InputNumber value={mfWeights.ep} onChange={v => setMfWeights(p => ({ ...p, ep: v || 0 }))} min={0} max={1} step={0.05} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item label="ROE权重">
            <InputNumber value={mfWeights.roe} onChange={v => setMfWeights(p => ({ ...p, roe: v || 0 }))} min={0} max={1} step={0.05} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item label="动量权重(20日)">
            <InputNumber value={mfWeights.momentum} onChange={v => setMfWeights(p => ({ ...p, momentum: v || 0 }))} min={0} max={1} step={0.05} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item label="市值权重(小市值)">
            <InputNumber value={mfWeights.market_cap} onChange={v => setMfWeights(p => ({ ...p, market_cap: v || 0 }))} min={0} max={1} step={0.05} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item label="选股数">
            <InputNumber value={mfTopN} onChange={v => setMfTopN(v || 10)} min={1} max={50} style={{ width: 70 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" loading={mfLoading} onClick={runMultifactor}>开始选股</Button>
          </Form.Item>
        </Form>

        <Spin spinning={mfLoading} tip="选股计算中…">
          {mfLoading && (
            <div style={{ padding: '20px 0' }}>
              <Progress percent={mfProgress} status={mfProgress >= 100 ? 'success' : 'active'} strokeColor="#1677ff" />
              <div style={{ textAlign: 'center', color: '#999', marginTop: 8 }}>
                正在扫描全市场股票…（{mfProgress}%）
              </div>
            </div>
          )}
          {mfResults.length > 0 && (
            <>
            <Table dataSource={mfResults} rowKey="code" size="small" pagination={false}
              scroll={{ x: 1100 }}
              columns={[
                { title: '排名', width: 50, render: (_: any, __: any, i: number) => i + 1 },
                { title: '代码', dataIndex: 'code', width: 90 },
                { title: '名称', dataIndex: 'name', width: 110 },
                { title: '类型', dataIndex: 'type', width: 60,
                  render: (v: string) => <Tag color={v === 'etf' ? 'blue' : 'default'}>{v === 'etf' ? 'ETF' : '股'}</Tag> },
                { title: '行业', dataIndex: 'industry', width: 100,
                  render: (v: string) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">-</Text> },
                { title: 'PE', dataIndex: 'pe', width: 70, align: 'right' as const, render: (v: any) => v != null ? v.toFixed(1) : '-' },
                { title: 'EP(1/PE)', dataIndex: 'ep', width: 80, align: 'right' as const, render: (v: any) => v != null ? v.toFixed(2) : '-' },
                { title: 'ROE%', dataIndex: 'roe', width: 80, align: 'right' as const, render: (v: any) => v != null ? v.toFixed(2) : '-' },
                { title: '涨跌幅%', dataIndex: 'momentum', width: 90, align: 'right' as const,
                  render: (v: any) => <span style={{ color: pctClr(v) }}>{v != null ? `${v > 0 ? '+' : ''}${v.toFixed(2)}%` : '-'}</span> },
                { title: '总市值(亿)', dataIndex: 'market_cap', width: 100, align: 'right' as const, render: (v: any) => v != null ? v.toFixed(1) : '-' },
                { title: '综合得分', dataIndex: 'total_score', width: 90, align: 'right' as const,
                  render: (v: any) => <Text strong style={{ color: '#1677ff' }}>{v != null ? v.toFixed(3) : '-'}</Text> },
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
            <Card
              title={<span><RobotOutlined style={{ marginRight: 8 }} />AI 分析报告</span>}
              style={{ marginTop: 16 }}
              extra={!aiLoading && !aiResult ? (
                <Button size="small" type="link" onClick={() => doAiAnalysis(mfResults)}>重新分析</Button>
              ) : null}
            >
              {aiLoading ? (
                <div style={{ textAlign: 'center', padding: '24px 0', color: '#999' }}>
                  <Spin /> <span style={{ marginLeft: 8 }}>AI 分析中，请稍候…</span>
                </div>
              ) : aiResult ? (
                <div className="ai-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{aiResult}</ReactMarkdown>
                </div>
              ) : (
                <Text type="secondary">暂无分析报告</Text>
              )}
            </Card>
          </>
          )}
          {!mfLoading && mfResults.length === 0 && (
            <Empty description="设置各因子权重后点击「开始选股」" />
          )}
        </Spin>
      </Card>

      {/* markdown 样式 */}
      <style>{`
        .ai-markdown { font-size: 14px; color: #333; line-height: 1.8; }
        .ai-markdown h1, .ai-markdown h2, .ai-markdown h3 { margin: 16px 0 8px; font-weight: 600; color: #1a1a1a; }
        .ai-markdown h1 { font-size: 18px; }
        .ai-markdown h2 { font-size: 16px; border-bottom: 1px solid #eee; padding-bottom: 6px; }
        .ai-markdown h3 { font-size: 15px; }
        .ai-markdown p { margin: 8px 0; }
        .ai-markdown ul, .ai-markdown ol { padding-left: 22px; margin: 8px 0; }
        .ai-markdown li { margin: 4px 0; }
        .ai-markdown strong { color: #1a1a1a; }
        .ai-markdown table { border-collapse: collapse; margin: 12px 0; width: 100%; }
        .ai-markdown th, .ai-markdown td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 13px; }
        .ai-markdown th { background: #fafafa; font-weight: 600; }
        .ai-markdown code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 13px; }
        .ai-markdown blockquote { border-left: 3px solid #ddd; margin: 8px 0; padding: 2px 12px; color: #666; }
        .ai-markdown hr { border: none; border-top: 1px solid #eee; margin: 16px 0; }
      `}</style>
    </div>
  )
}

