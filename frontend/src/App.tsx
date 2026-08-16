import { useState } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { ConfigProvider, App as AntApp, Layout, Menu, Dropdown, Avatar, Space, Modal, Form, Input, Grid, Drawer, Button } from 'antd'
import { SearchOutlined, StarOutlined, LineChartOutlined, SettingOutlined, StockOutlined, UserOutlined, LogoutOutlined, KeyOutlined, MenuOutlined } from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import StockQuery from './pages/StockQuery'
import Watchlist from './pages/Watchlist'
import Simulation from './pages/Simulation'
import Strategy from './pages/Strategy'
import StockSelection from './pages/StockSelection'
import Login from './pages/Login'
import { isLoggedIn, getUser, clearAuth } from './services/auth'
import { api } from './services/api'

const { Header, Content } = Layout

const menuItems = [
  { key: '/query', icon: <SearchOutlined />, label: '股票查询' },
  { key: '/watchlist', icon: <StarOutlined />, label: '自选股' },
  { key: '/simulation', icon: <LineChartOutlined />, label: '模拟交易' },
  { key: '/strategy', icon: <SettingOutlined />, label: '策略' },
  { key: '/selection', icon: <StockOutlined />, label: '选股分析' },
]

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = getUser()
  const { message } = AntApp.useApp()
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [changePwdOpen, setChangePwdOpen] = useState(false)
  const [changePwdLoading, setChangePwdLoading] = useState(false)
  const [changePwdForm] = Form.useForm()

  const handleLogout = () => {
    clearAuth()
    navigate('/login')
  }

  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key)
    setDrawerOpen(false)
  }

  const handleChangePassword = async (values: {
    old_password: string
    new_password: string
    confirm: string
  }) => {
    if (values.new_password !== values.confirm) {
      message.error('两次输入的新密码不一致')
      return
    }
    setChangePwdLoading(true)
    try {
      const { data } = await api.post('/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      if (data.code === 0) {
        message.success('密码修改成功')
        setChangePwdOpen(false)
        changePwdForm.resetFields()
      } else {
        message.error(data.message || '修改失败')
      }
    } catch (err: any) {
      message.error(err.response?.data?.detail || '修改失败')
    } finally {
      setChangePwdLoading(false)
    }
  }

  const userMenu = {
    items: [
      { key: 'changePwd', icon: <KeyOutlined />, label: '修改密码' },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'changePwd') {
        setChangePwdOpen(true)
      }
      if (key === 'logout') handleLogout()
    },
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', padding: '0 16px', gap: 12 }}>
        <h1 style={{ color: '#fff', margin: 0, fontSize: 16, whiteSpace: 'nowrap', flexShrink: 0 }}>
          📈 A股交易系统
        </h1>
        {isMobile ? (
          <>
            <Button type="text" icon={<MenuOutlined />} onClick={() => setDrawerOpen(true)} style={{ color: '#fff' }} />
            <div style={{ flex: 1 }} />
          </>
        ) : (
          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={[location.pathname]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ flex: 1, minWidth: 0 }}
          />
        )}
        <Dropdown menu={userMenu}>
          <Space style={{ color: '#fff', cursor: 'pointer', flexShrink: 0 }}>
            <Avatar size="small" icon={<UserOutlined />} />
            <span>{user?.username || '用户'}</span>
          </Space>
        </Dropdown>
      </Header>
      <Content style={{ padding: isMobile ? 12 : 24 }}>
        <Routes>
          <Route path="/query" element={<StockQuery />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/simulation" element={<Simulation />} />
          <Route path="/strategy" element={<Strategy />} />
          <Route path="/selection" element={<StockSelection />} />
          <Route path="*" element={<Navigate to="/query" replace />} />
        </Routes>
      </Content>

      <Drawer
        title="功能导航"
        placement="left"
        width={200}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <Menu
          mode="vertical"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={handleMenuClick}
        />
      </Drawer>

      <Modal
        title="修改密码"
        open={changePwdOpen}
        onOk={() => changePwdForm.submit()}
        onCancel={() => {
          setChangePwdOpen(false)
          changePwdForm.resetFields()
        }}
        confirmLoading={changePwdLoading}
        okText="确定"
        cancelText="取消"
      >
        <Form form={changePwdForm} onFinish={handleChangePassword} layout="vertical">
          <Form.Item name="old_password" label="旧密码" rules={[{ required: true, message: '请输入旧密码' }]}>
            <Input.Password placeholder="请输入旧密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 4, message: '新密码至少4个字符' },
            ]}
          >
            <Input.Password placeholder="请输入新密码" />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" rules={[{ required: true, message: '请再次输入新密码' }]}>
            <Input.Password placeholder="请再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          />
        </Routes>
      </AntApp>
    </ConfigProvider>
  )
}

