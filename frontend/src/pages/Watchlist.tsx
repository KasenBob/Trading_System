import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Table, Card, Button, Space, Tag, Typography, App, Spin,
  Select, Upload, Popconfirm, Switch, Tabs,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, ExportOutlined, ImportOutlined,
  ReloadOutlined, RiseOutlined, FallOutlined, MinusOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { api } from '../services/api'

const { Title, Text } = Typography

interface WatchItem {
  id: number; code: string; name: string; type: string; group: string; sort_order: number
}
interface QuoteRow extends WatchItem {
  price: number | null; change_pct: number | null; change_amount: number | null
  open: number | null; high: number | null; low: number | null
  pre_close: number | null; volume: number | null; amount: number | null
}

function pctClr(v: number | null) { return v == null ? '#999' : v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : '#999' }
function fmt(v: number | null | undefined, d = 2) { return v == null ? '-' : v.toFixed(d) }
function fmtVol(v: number | null | undefined): string {
  if (v == null) return '-'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return String(v)
}

export default function Watchlist() {
  const { message } = App.useApp(); const navigate = useNavigate()
  const [list, setList] = useState<WatchItem[]>([])
  const [quotes, setQuotes] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [refreshInterval, setRefreshInterval] = useState(10)
  const [activeGroup, setActiveGroup] = useState('全部')
  const timer = useRef<ReturnType<typeof setInterval>>(0)


  const loadList = useCallback(async () => {
    try { const { data } = await api.get('/watchlist'); setList(data.data ?? []) }
    catch { message.error('加载自选列表失败') }
  }, [message])

  const loadQuotes = useCallback(async (items: WatchItem[]) => {
    if (!items.length) { setQuotes({}); return }
    try {
      const { data } = await api.get('/market/realtime', { params: { codes: items.map(i => i.code).join(',') } })
      const map: Record<string, any> = {}
      ;(data.data ?? []).forEach((q: any) => { map[q.code] = q })
      setQuotes(map)
    } catch { /* 静默 */ }
  }, [])

  useEffect(() => { (async () => { setLoading(true); await loadList(); setLoading(false) })() }, [loadList])
  useEffect(() => { loadQuotes(list) }, [list, loadQuotes])

  useEffect(() => {
    if (autoRefresh && list.length) {
      timer.current = setInterval(() => { setRefreshing(true); loadQuotes(list).finally(() => setRefreshing(false)) }, refreshInterval * 1000)
      return () => clearInterval(timer.current)
    }
    return () => clearInterval(timer.current)
  }, [autoRefresh, refreshInterval, list, loadQuotes])

  const handleRefresh = async () => { setRefreshing(true); await loadQuotes(list); setRefreshing(false); message.success('已刷新') }
  const handleDelete = async (id: number) => { try { await api.delete(`/watchlist/${id}`); setList(p => p.filter(i => i.id !== id)); message.success('已删除') } catch { message.error('删除失败') } }
  const handleAdd = () => navigate('/query')

  const handleExport = () => {
    const rows = list.map(i => { const q = quotes[i.code] || {}; return [i.code, i.name, i.type, q.price ?? '', q.change_pct ?? ''].join(',') })
    const csv = '\uFEFF代码,名称,类型,现价,涨跌幅\n' + rows.join('\n')
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'watchlist.csv'; a.click()
    message.success('已导出')
  }

  const handleImport = (file: File) => {
    const reader = new FileReader()
    reader.onload = async e => {
      const lines = (e.target?.result as string).split('\n').slice(1).filter(Boolean)
      const items = lines.map(l => { const [code, name, type = 'stock'] = l.split(','); return { code: code.trim(), name: (name || '').trim(), type: type.trim(), group: '默认' } }).filter(i => i.code)
      if (!items.length) return message.warning('未识别到有效数据')
      try { await api.post('/watchlist/batch', { items }); await loadList(); message.success(`已导入 ${items.length} 只`) } catch { message.error('导入失败') }
    }; reader.readAsText(file); return false
  }

  const dataSource: QuoteRow[] = list
    .map(i => ({ ...i, ...(quotes[i.code] || {}) }))
    .filter(i => activeGroup === '全部' || i.group === activeGroup || (activeGroup === '股票' && i.type === 'stock') || (activeGroup === 'ETF' && i.type === 'etf'))

  const groups = ['全部', '股票', 'ETF', ...[...new Set(list.map(i => i.group))].filter(g => !['全部', '股票', 'ETF'].includes(g))]
  const upCount = dataSource.filter(d => (d.change_pct ?? 0) > 0).length
  const downCount = dataSource.filter(d => (d.change_pct ?? 0) < 0).length
  const totalPct = dataSource.reduce((s, d) => s + (d.change_pct ?? 0), 0)

  const columns: ColumnsType<QuoteRow> = [
    { title: '代码', dataIndex: 'code', width: 110,
      render: (v, r) => <a onClick={() => navigate(`/query?code=${r.code}`)}><Tag color={r.type === 'etf' ? 'blue' : 'default'} style={{ fontSize: 10, marginRight: 4 }}>{r.type === 'etf' ? 'ETF' : '股'}</Tag>{v}</a> },
    { title: '名称', dataIndex: 'name', width: 130 },
    { title: '现价', dataIndex: 'price', width: 90, align: 'right', render: (v, r) => <span style={{ color: pctClr(r.change_pct), fontWeight: 600 }}>{fmt(v)}</span> },
    { title: '涨跌幅', dataIndex: 'change_pct', width: 100, align: 'right',
      render: (v, r) => v == null ? <span style={{ color: '#999' }}>-</span> : <span style={{ color: pctClr(v) }}>{v > 0 ? <RiseOutlined /> : v < 0 ? <FallOutlined /> : <MinusOutlined />} {v > 0 ? '+' : ''}{v.toFixed(2)}%</span>,
      sorter: (a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0) },
    { title: '涨跌额', dataIndex: 'change_amount', width: 80, align: 'right', render: (v, r) => <span style={{ color: pctClr(r.change_pct) }}>{fmt(v)}</span> },
    { title: '开盘', dataIndex: 'open', width: 70, align: 'right', render: v => fmt(v) },
    { title: '最高', dataIndex: 'high', width: 70, align: 'right', render: v => fmt(v) },
    { title: '最低', dataIndex: 'low', width: 70, align: 'right', render: v => fmt(v) },
    { title: '成交量', dataIndex: 'volume', width: 90, align: 'right', render: v => fmtVol(v) },
    { title: '操作', width: 60, fixed: 'right', render: (_, r) => <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.id)}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm> },
  ]

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加自选</Button>
            <Upload accept=".csv" showUploadList={false} beforeUpload={handleImport}>
              <Button icon={<ImportOutlined />}>导入</Button>
            </Upload>
            <Button icon={<ExportOutlined />} onClick={handleExport}>导出</Button>
          </Space>
          <Space>
            <Text type="secondary">自动刷新</Text>
            <Switch size="small" checked={autoRefresh} onChange={setAutoRefresh} />
            {autoRefresh && <Select size="small" value={refreshInterval} onChange={setRefreshInterval}
              options={[{ value: 5, label: '5s' }, { value: 10, label: '10s' }, { value: 30, label: '30s' }]} style={{ width: 70 }} />}
            <Button icon={<ReloadOutlined spin={refreshing} />} onClick={handleRefresh} loading={refreshing}>刷新</Button>
          </Space>
        </div>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
          <div><Text type="secondary">总数 </Text><Text strong>{dataSource.length}</Text></div>
          <div><Text type="secondary">上涨 </Text><Text strong style={{ color: '#cf1322' }}>{upCount}</Text></div>
          <div><Text type="secondary">下跌 </Text><Text strong style={{ color: '#3f8600' }}>{downCount}</Text></div>
          <div><Text type="secondary">平均涨跌 </Text>
            <Text strong style={{ color: pctClr(dataSource.length ? totalPct / dataSource.length : null) }}>
              {dataSource.length ? (totalPct / dataSource.length).toFixed(2) : '-'}%
            </Text>
          </div>
        </div>
      </Card>

      <Card>
        <Tabs activeKey={activeGroup} onChange={setActiveGroup} style={{ marginBottom: -8 }}
          items={groups.map(g => ({ key: g, label: g }))} />
        <Spin spinning={loading}>
          <Table<QuoteRow> dataSource={dataSource} columns={columns} rowKey="id"
            size="small" pagination={false} scroll={{ x: 1000 }}
            locale={{ emptyText: '暂无自选股，去「股票查询」页搜索并点击「加入自选」' }} />
        </Spin>
      </Card>
    </div>
  )
}

