import { useQuery } from "@tanstack/react-query";
import {
  App as AntApp,
  Avatar,
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  Input,
  Layout,
  Menu,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";
import {
  AlertOutlined,
  ApartmentOutlined,
  AuditOutlined,
  BellOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MedicineBoxOutlined,
  SearchOutlined,
  SettingOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { useState } from "react";
import { fetchApiHealth } from "./lib/health";

const { Header, Sider, Content } = Layout;
const { Text, Title } = Typography;

const modules = [
  { key: "overview", icon: <DashboardOutlined />, label: "Overview" },
  { key: "registration", icon: <TeamOutlined />, label: "Registration" },
  { key: "opd", icon: <MedicineBoxOutlined />, label: "OPD queue" },
  { key: "ipd", icon: <ApartmentOutlined />, label: "IPD & beds" },
  { key: "quality", icon: <AuditOutlined />, label: "Quality OS" },
  { key: "integrations", icon: <DatabaseOutlined />, label: "Integrations" },
];

function App() {
  const [collapsed, setCollapsed] = useState(false);
  const [activeModule, setActiveModule] = useState("overview");
  const [search, setSearch] = useState("");
  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchApiHealth,
    retry: false,
    refetchInterval: 30_000,
  });

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#0f766e",
          colorInfo: "#0f766e",
          borderRadius: 6,
          fontFamily: "'DM Sans', 'Segoe UI', sans-serif",
        },
      }}
    >
      <AntApp>
        <Layout className="app-shell">
          <Sider className="app-sider" trigger={null} collapsible collapsed={collapsed} width={248}>
            <div className="brand-lockup">
              <div className="brand-mark">M</div>
              {!collapsed && (
                <div>
                  <div className="brand-name">Mediflow OS</div>
                  <div className="brand-caption">Hospital operations</div>
                </div>
              )}
            </div>
            <Menu
              mode="inline"
              selectedKeys={[activeModule]}
              items={modules}
              onClick={({ key }) => setActiveModule(key)}
            />
            <div className="sider-footer">
              {!collapsed && <Text type="secondary">Facility workspace</Text>}
              <Button type="text" icon={<SettingOutlined />} aria-label="Settings" />
            </div>
          </Sider>
          <Layout>
            <Header className="app-header">
              <Space size="middle">
                <Button
                  type="text"
                  icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                  onClick={() => setCollapsed(!collapsed)}
                  aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
                />
                <div className="header-context">
                  <Text type="secondary">Facility</Text>
                  <Text strong>District Hospital / Main Campus</Text>
                </div>
              </Space>
              <Space size="large">
                <Badge dot color="#ef4444">
                  <Button type="text" icon={<BellOutlined />} aria-label="Notifications" />
                </Badge>
                <Avatar className="user-avatar">AS</Avatar>
              </Space>
            </Header>
            <Content className="app-content">
              <div className="page-heading">
                <div>
                  <Text className="eyebrow">Wednesday, 1 October 2026</Text>
                  <Title level={2}>Good morning, Ananya</Title>
                  <Text type="secondary">Here is the operational picture for your facility.</Text>
                </div>
                <Space>
                  <Tag color={health.isSuccess ? "success" : "warning"}>
                    {health.isSuccess ? "API connected" : "API offline"}
                  </Tag>
                  <Button type="primary" icon={<SearchOutlined />}>Find patient</Button>
                </Space>
              </div>

              <div className="search-strip">
                <Input
                  allowClear
                  size="large"
                  prefix={<SearchOutlined />}
                  placeholder="Search UHID, patient name or ABHA address"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <Text type="secondary">Use the patient workspace to review encounters and registration status.</Text>
              </div>

              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12} xl={6}><Card><Statistic title="Patients today" value={128} suffix={<span className="stat-delta">+12%</span>} /></Card></Col>
                <Col xs={24} sm={12} xl={6}><Card><Statistic title="OPD waiting" value={24} valueStyle={{ color: "#d97706" }} /></Card></Col>
                <Col xs={24} sm={12} xl={6}><Card><Statistic title="Bed occupancy" value={76} suffix="%" /></Card></Col>
                <Col xs={24} sm={12} xl={6}><Card><Statistic title="Open CAPAs" value={7} valueStyle={{ color: "#b45309" }} /></Card></Col>
              </Row>

              <Row gutter={[16, 16]} className="dashboard-grid">
                <Col xs={24} xl={15}>
                  <Card title="Today at a glance" extra={<Button type="link">View report</Button>}>
                    <div className="queue-list">
                      {[
                        ["OPD registration", "128 patients registered", "Live"],
                        ["Admissions", "9 new · 3 transfers", "Updated 2m ago"],
                        ["Quality OS", "4 indicators need attention", "Review"],
                      ].map(([title, detail, state]) => (
                        <div className="queue-row" key={title}>
                          <div><Text strong>{title}</Text><br /><Text type="secondary">{detail}</Text></div>
                          <Tag color={state === "Live" ? "success" : state === "Review" ? "warning" : "default"}>{state}</Tag>
                        </div>
                      ))}
                    </div>
                  </Card>
                </Col>
                <Col xs={24} xl={9}>
                  <Card title="Attention required" extra={<AlertOutlined className="attention-icon" />}>
                    <div className="attention-item"><span className="priority-dot critical" /><div><Text strong>3 beds awaiting cleaning</Text><br /><Text type="secondary">Medical ward · review status</Text></div></div>
                    <div className="attention-item"><span className="priority-dot warning" /><div><Text strong>Monthly data quality check</Text><br /><Text type="secondary">4 indicators have missing inputs</Text></div></div>
                    <Button block className="attention-button">Open worklist</Button>
                  </Card>
                </Col>
              </Row>
            </Content>
          </Layout>
        </Layout>
      </AntApp>
    </ConfigProvider>
  );
}

export default App;
