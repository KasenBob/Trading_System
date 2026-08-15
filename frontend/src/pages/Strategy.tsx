import { useState, useEffect, useCallback } from 'react'
import { Card, Table, Button, Form, InputNumber, Input, Tag, Typography, App, Spin, Empty, Descriptions, Switch, Select, Modal, Space, Tooltip } from 'antd'
import { PlayCircleOutlined, PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { api } from '../services/api'

const { Title, Text } = Typography

function fmt(v: any, d = 2) { return v == null ? '-' : Number(v).toFixed(d) }
function pctClr(v: any) { const n = Number(v); return isNaN(n) ? '#999' : n > 0 ? '#cf1322' : n < 0 ? '#3f8600' : '#999' }

// 日期格式化：YYYYMMDD
function fmtDate(d: Date) {
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}
// 当天
const TODAY = fmtDate(new Date())
// 回测默认起始日期：2023年1月1日
const DEFAULT_BT_START = '20230101'

const PRESET_STRATEGIES = [
  { name: '双均线交叉', type: 'ma_cross', params: { fast: 5, slow: 20 } },
  { name: 'MACD金叉死叉', type: 'macd', params: { fast: 12, slow: 26, signal_period: 9, ma_filter: 60 } },
  { name: '布林带突破', type: 'bollinger', params: { period: 20, std: 2.0 } },
  { name: 'RSI超买超卖', type: 'rsi', params: { period: 14, oversold: 30, overbought: 70 } },
  { name: 'KDJ随机指标', type: 'kdj', params: { n: 9, k_period: 3, d_period: 3 } },
  { name: '单边上升策略', type: 'uptrend', params: { fast: 5, trail_pct: 8 } },
  { name: '震荡盘整策略', type: 'oscillation', params: {
    boll_period: 20, boll_std: 2.0, rsi_period: 14,
    rsi_oversold: 30, rsi_overbought: 70, kdj_n: 9,
    kdj_k: 3, kdj_d: 3, j_oversold: 0, j_overbought: 100 } },
]

// 各策略类型的参数字段定义（字段名 → 中文标签）
const PARAM_FIELDS: Record<string, { key: string; label: string; step?: number }[]> = {
  ma_cross: [
    { key: 'fast', label: '快线周期' },
    { key: 'slow', label: '慢线周期' },
  ],
  macd: [
    { key: 'fast', label: '快线EMA' },
    { key: 'slow', label: '慢线EMA' },
    { key: 'signal_period', label: '信号线周期' },
    { key: 'ma_filter', label: '60日均线周期' },
  ],
  bollinger: [
    { key: 'period', label: '周期' },
    { key: 'std', label: '标准差倍数', step: 0.1 },
  ],
  rsi: [
    { key: 'period', label: '周期' },
    { key: 'oversold', label: '超卖线' },
    { key: 'overbought', label: '超买线' },
  ],
  kdj: [
    { key: 'n', label: 'N日' },
    { key: 'k_period', label: 'K周期' },
    { key: 'd_period', label: 'D周期' },
  ],
  uptrend: [
    { key: 'fast', label: '买入均线周期' },
    { key: 'trail_pct', label: '回撤止损%', step: 1 },
  ],
  oscillation: [
    { key: 'boll_period', label: '布林周期' },
    { key: 'boll_std', label: '布林标准差倍数', step: 0.1 },
    { key: 'rsi_period', label: 'RSI周期' },
    { key: 'rsi_oversold', label: 'RSI超卖线' },
    { key: 'rsi_overbought', label: 'RSI超买线' },
    { key: 'kdj_n', label: 'KDJ N日' },
    { key: 'kdj_k', label: 'KDJ K周期' },
    { key: 'kdj_d', label: 'KDJ D周期' },
    { key: 'j_oversold', label: 'J超卖线' },
    { key: 'j_overbought', label: 'J超买线' },
  ],
}

export default function Strategy() {
  const { message } = App.useApp()
  const [strategies, setStrategies] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [btLoading, setBtLoading] = useState(false)
  const [btResults, setBtResults] = useState<any[]>([])
  const [btIndexData, setBtIndexData] = useState<any[]>([])
  const [watchlist, setWatchlist] = useState<any[]>([])
  const [btCode, setBtCode] = useState('')
  const [btStart, setBtStart] = useState(DEFAULT_BT_START)
  const [btEnd, setBtEnd] = useState(TODAY)
  const [btCapital, setBtCapital] = useState(100000)
  const [btCombine, setBtCombine] = useState('separate')
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [editParams, setEditParams] = useState<Record<string, any>>({})

  // 加载自选股列表
  const loadWatchlist = useCallback(async () => {
    try {
      const { data } = await api.get('/watchlist')
      const wl = data.data ?? []
      setWatchlist(wl)
      if (wl.length && !btCode) setBtCode(wl[0].code)
    } catch { /* 静默 */ }
  }, [btCode])

  useEffect(() => { loadWatchlist() }, [])

  const loadStrategies = useCallback(async () => {
    setLoading(true)
    try { const { data } = await api.get('/strategy'); setStrategies(data.data) }
    catch { message.error('加载策略失败') }
    finally { setLoading(false) }
  }, [message])

  useEffect(() => { loadStrategies() }, [loadStrategies])

  const addPreset = async (preset: any) => {
    try { await api.post('/strategy', preset); loadStrategies(); message.success(`已添加 ${preset.name}`) }
    catch { message.error('添加失败') }
  }

  const deleteStrategy = async (id: number) => {
    try { await api.delete(`/strategy/${id}`); loadStrategies(); message.success('已删除') }
    catch { message.error('删除失败') }
  }

  // 打开编辑弹窗
  const openEdit = (s: any) => {
    let params: Record<string, any> = {}
    try { params = JSON.parse(s.params) } catch { params = {} }
    setEditing(s)
    setEditParams(params)
    setEditOpen(true)
  }

  // 保存参数
  const saveEdit = async () => {
    if (!editing) return
    try {
      await api.put(`/strategy/${editing.id}`, {
        name: editing.name, type: editing.type, params: editParams,
      })
      message.success('参数已更新')
      setEditOpen(false)
      loadStrategies()
    } catch { message.error('更新失败') }
  }

  const toggleStrategy = async (id: number) => {
    try { await api.put(`/strategy/${id}/toggle`); loadStrategies() }
    catch { message.error('操作失败') }
  }

  const runBacktest = async () => {
    if (!btCode) return message.warning('请先选择自选股')
    setBtLoading(true); setBtResults([])
    try {
      const [btRes, idxRes] = await Promise.all([
        api.post('/strategy/backtest', {
          code: btCode, start_date: btStart, end_date: btEnd, initial_capital: btCapital,
          combine: btCombine,
        }),
        api.get('/market/index/sh000300'),
      ])
      setBtResults(btRes.data.data)
      setBtIndexData(idxRes.data.data ?? [])
      message.success('回测完成')
    } catch (err: any) { message.error(err.response?.data?.detail || '回测失败') }
    finally { setBtLoading(false) }
  }

  const makeChartOption = (dailyValues: any[]) => {
    const base = dailyValues.length > 0 ? dailyValues[0].total_asset : 0
    const dates = dailyValues.map((d: any) => String(d.date))
    const assetLine = dailyValues.map((d: any) =>
      base > 0 ? Number(((d.total_asset / base - 1) * 100).toFixed(2)) : 0)

    // 沪深300基准：按回测交易日对齐
    const idxMap = new Map(btIndexData.map((d: any) => [String(d.date), d.close]))
    const startDate = dates[0]
    const idxBase = idxMap.get(startDate)
      ?? btIndexData.find((d: any) => String(d.date) >= startDate)?.close
      ?? btIndexData[0]?.close
    const indexLine = dates.map((date: string) => {
      const idx = idxMap.get(date)
      if (idx == null || idxBase == null) return null
      return Number(((idx / idxBase - 1) * 100).toFixed(2))
    })

    return {
      animation: false,
      tooltip: { trigger: 'axis', valueFormatter: (v: any) => (v == null ? '-' : `${v}%`) },
      legend: { data: ['策略收益率', '沪深300'], top: 0 },
      xAxis: { type: 'category', data: dates },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
      series: [
        {
          type: 'line', name: '策略收益率', data: assetLine,
          smooth: true, symbol: 'none', lineStyle: { color: '#1677ff', width: 2 },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: 'rgba(22,119,255,0.2)' }, { offset: 1, color: 'rgba(22,119,255,0.02)' }] } },
        },
        { type: 'line', name: '沪深300', data: indexLine,
          smooth: true, symbol: 'none', lineStyle: { color: '#faad14', width: 1.5, type: 'dashed' } },
      ],
    }
  }

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <Card title="策略模板" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {PRESET_STRATEGIES.map(p => (
            <Card key={p.type} size="small" style={{ width: 200 }}
              actions={[<Button type="link" icon={<PlusOutlined />} onClick={() => addPreset(p)}>添加</Button>]}>
              <Title level={5} style={{ margin: 0 }}>{p.name}</Title>
              <Tooltip title={Object.entries(p.params).map(([k, v]) => `${k}=${v}`).join(', ')}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block' }} ellipsis>
                  {Object.entries(p.params).map(([k, v]) => `${k}=${v}`).join(', ')}
                </Text>
              </Tooltip>
            </Card>
          ))}
        </div>
        <Spin spinning={loading}>
          {strategies.length > 0 && (
            <Table dataSource={strategies} rowKey="id" size="small" style={{ marginTop: 16 }} pagination={false}
              columns={[
                { title: '名称', dataIndex: 'name' },
                { title: '启用', dataIndex: 'enabled', width: 60,
                  render: (v: boolean, r: any) => <Switch size="small" checked={v} onChange={() => toggleStrategy(r.id)} /> },
                { title: '类型', dataIndex: 'type', render: (v: string) => <Tag>{v}</Tag> },
                { title: '参数', dataIndex: 'params', width: 240, ellipsis: true, render: (v: string) => { try { return JSON.stringify(JSON.parse(v)) } catch { return v } } },
                { title: '操作', width: 120, render: (_: any, r: any) => (
                  <Space size={0}>
                    <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(r)} />
                    <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => deleteStrategy(r.id)} />
                  </Space>
                ) },
              ]} />
          )}
        </Spin>
      </Card>

      <Card title="回测">
        <Form layout="inline" style={{ marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
          <Form.Item label="标的">
            <Select
              value={btCode}
              onChange={setBtCode}
              style={{ width: 180 }}
              placeholder="选择自选股"
              showSearch
              optionFilterProp="label"
              options={watchlist.map((w: any) => ({
                value: w.code,
                label: `${w.code} ${w.name}`,
              }))}
              notFoundContent={watchlist.length ? undefined : '暂无自选股，请先在自选股页添加'}
            />
          </Form.Item>
          <Form.Item label="起始"><Input value={btStart} onChange={e => setBtStart(e.target.value)} style={{ width: 100 }} /></Form.Item>
          <Form.Item label="截止"><Input value={btEnd} onChange={e => setBtEnd(e.target.value)} style={{ width: 100 }} /></Form.Item>
          <Form.Item label="资金"><InputNumber value={btCapital} onChange={v => setBtCapital(v || 100000)} min={10000} step={10000} style={{ width: 100 }} /></Form.Item>
          <Form.Item label="组合方式">
            <Select value={btCombine} onChange={setBtCombine} style={{ width: 110 }}
              options={[
                { value: 'separate', label: '各自对比' },
                { value: 'filter', label: '多层过滤' },
                { value: 'and', label: 'AND共振' },
                { value: 'vote', label: '投票制' },
              ]} />
          </Form.Item>
          <Form.Item><Button type="primary" icon={<PlayCircleOutlined />} loading={btLoading} onClick={runBacktest}>运行回测</Button></Form.Item>
        </Form>
        <Spin spinning={btLoading} tip="回测运行中…">
          {btResults.map((r: any, idx: number) => (
            <Card key={idx} title={r.strategy_name || `策略${idx + 1}`} style={{ marginBottom: 16 }}>
              {r.error ? <Text type="danger">{r.error}</Text> : (
                <>
                  <Descriptions column={4} size="small" bordered style={{ marginBottom: 16 }}>
                    <Descriptions.Item label="初始资金">¥{fmt(r.initial_capital, 0)}</Descriptions.Item>
                    <Descriptions.Item label="最终资产">¥{fmt(r.final_asset, 0)}</Descriptions.Item>
                    <Descriptions.Item label="总收益率"><Text style={{ color: pctClr(r.total_return) }}>{r.total_return > 0 ? '+' : ''}{fmt(r.total_return)}%</Text></Descriptions.Item>
                    <Descriptions.Item label="年化收益">{r.annual_return > 0 ? '+' : ''}{fmt(r.annual_return)}%</Descriptions.Item>
                    <Descriptions.Item label="夏普比率"><Text style={{ color: pctClr(r.sharpe) }}>{fmt(r.sharpe)}</Text></Descriptions.Item>
                    <Descriptions.Item label="年化波动率">{fmt(r.volatility)}%</Descriptions.Item>
                    <Descriptions.Item label="最大回撤"><Text type="danger">{fmt(r.max_drawdown)}%</Text></Descriptions.Item>
                    <Descriptions.Item label="胜率">{fmt(r.win_rate)}%</Descriptions.Item>
                    <Descriptions.Item label="盈亏比"><Text style={{ color: pctClr(r.profit_loss_ratio) }}>{fmt(r.profit_loss_ratio)}</Text></Descriptions.Item>
                    <Descriptions.Item label="盈利因子"><Text style={{ color: pctClr(r.profit_factor) }}>{fmt(r.profit_factor)}</Text></Descriptions.Item>
                    <Descriptions.Item label="交易次数">{r.trade_count}</Descriptions.Item>
                  </Descriptions>
                  {r.daily_values?.length > 0 && <ReactECharts option={makeChartOption(r.daily_values)} style={{ height: 300 }} />}
                  {r.trades?.length > 0 && (
                    <Table dataSource={[...r.trades].reverse()} rowKey={(_, i) => String(i)} size="small" style={{ marginTop: 16 }}
                      columns={[
                        { title: '日期', dataIndex: 'date', width: 110 },
                        { title: '方向', dataIndex: 'direction', width: 60,
                          render: (v: string) => <Tag color={v === 'buy' ? 'red' : 'green'}>{v === 'buy' ? '买' : '卖'}</Tag> },
                        { title: '价格', dataIndex: 'price', width: 80, align: 'right' as const },
                        { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' as const },
                        { title: '金额', dataIndex: 'amount', width: 100, align: 'right' as const },
                        { title: '手续费', dataIndex: 'fee', width: 80, align: 'right' as const },
                      ]} />
                  )}
                </>
              )}
            </Card>
          ))}
          {!btLoading && btResults.length === 0 && <Empty description="添加策略模板后，设置回测参数并点击运行" />}
        </Spin>
      </Card>

      {/* 编辑参数弹窗 */}
      <Modal
        title={`编辑策略参数 - ${editing?.name || ''}`}
        open={editOpen}
        onOk={saveEdit}
        onCancel={() => setEditOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        {editing && (
          <Form layout="vertical">
            {(PARAM_FIELDS[editing.type] || []).map(f => (
              <Form.Item key={f.key} label={f.label}>
                <InputNumber
                  value={editParams[f.key]}
                  onChange={v => setEditParams(prev => ({ ...prev, [f.key]: v }))}
                  step={f.step || 1}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            ))}
          </Form>
        )}
      </Modal>
    </div>
  )
}
