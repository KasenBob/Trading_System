import axios from 'axios'
import { getToken, clearAuth } from './auth'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

// 请求拦截器：自动带 token
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：401 跳转登录
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      clearAuth()
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export { api }


export interface QuoteData {
  code: string
  name: string
  price: number | null
  open: number | null
  high: number | null
  low: number | null
  pre_close: number | null
  change_pct: number | null
  change_amount: number | null
  volume: number | null
  amount: number | null
}

export interface StockInfo {
  [key: string]: string
}

export interface StockDetail {
  code: string
  quote: QuoteData
  info: StockInfo
}

export interface KlineItem {
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
}

export interface SearchItem {
  code: string
  name: string
  type?: string
}

/** 搜索股票 */
export async function searchStocks(keyword: string): Promise<SearchItem[]> {
  const { data } = await api.get('/stock/search', { params: { keyword } })
  return data.data ?? []
}

/** 个股详情 */
export async function getStockDetail(code: string): Promise<StockDetail> {
  const { data } = await api.get(`/stock/detail/${code}`)
  return data.data
}

/** K线数据 */
export async function getKline(
  code: string,
  period: string = 'daily',
  startDate?: string,
  endDate?: string,
): Promise<KlineItem[]> {
  const { data } = await api.get('/market/kline', {
    params: { code, period, start_date: startDate, end_date: endDate },
  })
  return data.data ?? []
}

export interface MinuteItem {
  time: string
  price: number
  volume: number
  cum_volume: number
  avg_price: number
}

export interface FundFlowItem {
  date: string
  main_net_inflow: number
  retail_net_inflow: number
  mid_net_inflow: number
  large_net_inflow: number
  super_large_net_inflow: number
  main_pct: number
}

/** 分时数据 */
export async function getMinuteData(code: string): Promise<MinuteItem[]> {
  const { data } = await api.get(`/stock/minute/${code}`)
  return data.data ?? []
}

/** 资金流向 */
export async function getFundFlow(code: string, days: number = 60): Promise<FundFlowItem[]> {
  const { data } = await api.get(`/stock/fundflow/${code}`, { params: { days } })
  return data.data ?? []
}

export interface FinancialItem {
  date: string
  eps: number | null
  bps: number | null
  roe: number | null
  profit_growth: number | null
  revenue_growth: number | null
  debt_ratio: number | null
  total_asset: number | null
}

/** 个股财务指标 */
export async function getStockFinancial(code: string): Promise<FinancialItem[]> {
  const { data } = await api.get(`/stock/financial/${code}`)
  return data.data ?? []
}

