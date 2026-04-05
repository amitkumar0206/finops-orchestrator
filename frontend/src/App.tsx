import React, { useState, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import {
  Box,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
} from '@mui/material';
import {
  Logout as LogoutIcon,
  HomeOutlined as HomeOutlinedIcon,
  ForumOutlined as ForumOutlinedIcon,
  InsightsOutlined as InsightsOutlinedIcon,
  AutoFixHighOutlined as AutoFixHighOutlinedIcon,
  ReceiptLongOutlined as ReceiptLongOutlinedIcon,
  SettingsOutlined as SettingsOutlinedIcon,
  AdminPanelSettings as AdminPanelSettingsIcon,
  PersonOutline as PersonOutlineIcon,
} from '@mui/icons-material';

import ChatInterface from './components/Chat/ChatInterface';
import LoginPage from './pages/LoginPage';
import LandingPage from './pages/LandingPage';
import IacWorkbenchPage from './pages/IacWorkbenchPage';
import CurAnalysisPage from './pages/CurAnalysisPage';
import GenerateBlueprintPage from './pages/GenerateBlueprintPage';
import SettingsPage from './pages/SettingsPage';
import ProfilePage from './pages/ProfilePage';
import AdminConsolePage from './pages/AdminConsolePage';
import ErrorBoundary from './components/ErrorBoundary';
import { ScopeIndicator } from './components/Scope';
import { AuthProvider, useAuth } from './context/AuthContext';

const AppShell: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAuthenticated, isCheckingAuth, logout, canAccess } = useAuth();
  const [scopeVersion, setScopeVersion] = useState(0);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(true);

  useEffect(() => {
    setIsSidebarCollapsed(true);
  }, [location.pathname]);

  const handleScopeChange = () => {
    setScopeVersion((v) => v + 1);
  };

  const handleLogout = async () => {
    await logout();
    navigate('/');
  };

  if (isCheckingAuth) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          background: 'linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)',
        }}
      >
        <Box sx={{ color: 'white', textAlign: 'center' }}>
          <div style={{ fontSize: '24px', marginBottom: '20px' }}>Loading...</div>
        </Box>
      </Box>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  const activeRoute = (() => {
    if (location.pathname === '/' || location.pathname.startsWith('/home')) return '/';
    if (location.pathname.startsWith('/generate')) return '/generate';
    if (location.pathname.startsWith('/cur-analysis')) return '/cur-analysis';
    if (location.pathname.startsWith('/iac') || location.pathname.startsWith('/analyze')) return '/analyze';
    if (location.pathname.startsWith('/settings')) return '/settings';
    if (location.pathname.startsWith('/profile')) return '/profile';
    if (location.pathname.startsWith('/admin')) return '/admin';
    return '/chat';
  })();

  const hideSidebar = location.pathname === '/' || location.pathname.startsWith('/home');

  const navItems = [
    canAccess('chat') ? { key: '/chat', label: 'Cost Chat', icon: <ForumOutlinedIcon sx={{ fontSize: 20 }} /> } : null,
    canAccess('analyze') ? { key: '/analyze', label: 'Analyze', icon: <InsightsOutlinedIcon sx={{ fontSize: 20 }} /> } : null,
    canAccess('generate') ? { key: '/generate', label: 'Generate', icon: <AutoFixHighOutlinedIcon sx={{ fontSize: 20 }} /> } : null,
    canAccess('cur_analysis') ? { key: '/cur-analysis', label: 'CUR Analysis', icon: <ReceiptLongOutlinedIcon sx={{ fontSize: 20 }} /> } : null,
    canAccess('admin_console') ? { key: '/admin', label: 'Admin', icon: <AdminPanelSettingsIcon sx={{ fontSize: 20 }} /> } : null,
  ].filter(Boolean) as Array<{ key: string; label: string; icon: React.ReactNode }>;

  const chatRouteElement = canAccess('chat') ? <ErrorBoundary><ChatInterface key={scopeVersion} /></ErrorBoundary> : <Navigate to="/" replace />;
  const analyzeRouteElement = canAccess('analyze') ? <ErrorBoundary><IacWorkbenchPage /></ErrorBoundary> : <Navigate to="/" replace />;
  const curAnalysisRouteElement = canAccess('cur_analysis') ? <ErrorBoundary><CurAnalysisPage /></ErrorBoundary> : <Navigate to="/" replace />;
  const generateRouteElement = canAccess('generate') ? <ErrorBoundary><GenerateBlueprintPage /></ErrorBoundary> : <Navigate to="/" replace />;
  const adminRouteElement = canAccess('admin_console') ? <ErrorBoundary><AdminConsolePage /></ErrorBoundary> : <Navigate to="/" replace />;

  return (
    <Box sx={{ display: 'flex', height: '100vh', bgcolor: '#f8fafc' }}>
      {!hideSidebar && (
        <Box
          onMouseEnter={() => setIsSidebarCollapsed(false)}
          onMouseLeave={() => setIsSidebarCollapsed(true)}
          sx={{
            width: isSidebarCollapsed ? 76 : 248,
            transition: 'width 0.22s ease',
            bgcolor: '#ffffff',
            borderRight: '1px solid rgba(15, 23, 42, 0.08)',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
          }}
        >
          {/* Logo */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              px: isSidebarCollapsed ? 0.75 : 1.5,
              py: 1.25,
              borderBottom: '1px solid rgba(15, 23, 42, 0.06)',
            }}
          >
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: isSidebarCollapsed ? 38 : '100%',
                height: 38,
                borderRadius: 1.4,
                bgcolor: isSidebarCollapsed ? '#1565C0' : 'transparent',
              }}
            >
              {isSidebarCollapsed ? (
                <img src="/aasmaa-icon.png" alt="aasmaa" style={{ width: 22, height: 22, filter: 'brightness(0) invert(1)' }} />
              ) : (
                <img src="/aasmaa-logo.png" alt="aasmaa.ai" style={{ height: 32, maxWidth: 180 }} />
              )}
            </Box>
          </Box>

          {!isSidebarCollapsed && (
            <Box sx={{ px: 1.25, pt: 0.5, pb: 0.25 }}>
              <ScopeIndicator onScopeChange={handleScopeChange} />
            </Box>
          )}

          {/* Top nav: Home + dynamic nav items */}
          <List sx={{ px: isSidebarCollapsed ? 0.9 : 1.2, pb: 0.5 }}>
            <ListItem disablePadding sx={{ mb: 0.5 }}>
              <Tooltip title={isSidebarCollapsed ? 'Home' : ''} placement="right">
                <ListItemButton
                  component={Link}
                  to="/"
                  selected={activeRoute === '/'}
                  sx={{
                    borderRadius: 2,
                    minHeight: 44,
                    justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                    px: isSidebarCollapsed ? 1 : 1.3,
                    color: activeRoute === '/' ? '#0D47A1' : '#334155',
                    bgcolor: activeRoute === '/' ? 'rgba(21,101,192,0.12)' : 'transparent',
                    '&:hover': {
                      bgcolor: activeRoute === '/' ? 'rgba(21,101,192,0.16)' : 'rgba(15,23,42,0.05)',
                    },
                  }}
                >
                  <ListItemIcon
                    sx={{ minWidth: isSidebarCollapsed ? 0 : 34, color: 'inherit' }}
                  >
                    <HomeOutlinedIcon sx={{ fontSize: 20 }} />
                  </ListItemIcon>
                  {!isSidebarCollapsed && (
                    <ListItemText
                      primary="Home"
                      primaryTypographyProps={{ fontSize: '0.92rem', fontWeight: 600 }}
                    />
                  )}
                </ListItemButton>
              </Tooltip>
            </ListItem>

            {navItems.map((item) => (
              <ListItem key={item.key} disablePadding sx={{ mb: 0.5 }}>
                <Tooltip title={isSidebarCollapsed ? item.label : ''} placement="right">
                  <ListItemButton
                    component={Link}
                    to={item.key}
                    selected={activeRoute === item.key}
                    sx={{
                      borderRadius: 2,
                      minHeight: 44,
                      justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                      px: isSidebarCollapsed ? 1 : 1.3,
                      color: activeRoute === item.key ? '#0D47A1' : '#334155',
                      bgcolor: activeRoute === item.key ? 'rgba(21,101,192,0.12)' : 'transparent',
                      '&:hover': {
                        bgcolor: activeRoute === item.key ? 'rgba(21,101,192,0.16)' : 'rgba(15,23,42,0.05)',
                      },
                    }}
                  >
                    <ListItemIcon
                      sx={{ minWidth: isSidebarCollapsed ? 0 : 34, color: 'inherit' }}
                    >
                      {item.icon}
                    </ListItemIcon>
                    {!isSidebarCollapsed && (
                      <ListItemText
                        primary={item.label}
                        primaryTypographyProps={{ fontSize: '0.92rem', fontWeight: 600 }}
                      />
                    )}
                  </ListItemButton>
                </Tooltip>
              </ListItem>
            ))}
          </List>

          <Box sx={{ flexGrow: 1 }} />

          {/* Bottom nav: Settings, Profile, Logout */}
          <List sx={{ px: isSidebarCollapsed ? 0.9 : 1.2, pb: 1.2 }}>
            <ListItem disablePadding sx={{ mb: 0.5 }}>
              <Tooltip title={isSidebarCollapsed ? 'Settings' : ''} placement="right">
                <ListItemButton
                  component={Link}
                  to="/settings"
                  selected={activeRoute === '/settings'}
                  sx={{
                    borderRadius: 2,
                    minHeight: 42,
                    justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                    px: isSidebarCollapsed ? 1 : 1.3,
                    color: activeRoute === '/settings' ? '#0D47A1' : '#334155',
                    bgcolor: activeRoute === '/settings' ? 'rgba(21,101,192,0.12)' : 'transparent',
                    '&:hover': { bgcolor: activeRoute === '/settings' ? 'rgba(21,101,192,0.16)' : 'rgba(15,23,42,0.05)' },
                  }}
                >
                  <ListItemIcon sx={{ minWidth: isSidebarCollapsed ? 0 : 34, color: '#334155' }}>
                    <SettingsOutlinedIcon sx={{ fontSize: 20 }} />
                  </ListItemIcon>
                  {!isSidebarCollapsed && <ListItemText primary="Settings" primaryTypographyProps={{ fontSize: '0.9rem' }} />}
                </ListItemButton>
              </Tooltip>
            </ListItem>

            <ListItem disablePadding sx={{ mb: 0.5 }}>
              <Tooltip title={isSidebarCollapsed ? 'Profile' : ''} placement="right">
                <ListItemButton
                  component={Link}
                  to="/profile"
                  selected={activeRoute === '/profile'}
                  sx={{
                    borderRadius: 2,
                    minHeight: 42,
                    justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                    px: isSidebarCollapsed ? 1 : 1.3,
                    color: activeRoute === '/profile' ? '#0D47A1' : '#334155',
                    bgcolor: activeRoute === '/profile' ? 'rgba(21,101,192,0.12)' : 'transparent',
                    '&:hover': { bgcolor: activeRoute === '/profile' ? 'rgba(21,101,192,0.16)' : 'rgba(15,23,42,0.05)' },
                  }}
                >
                  <ListItemIcon sx={{ minWidth: isSidebarCollapsed ? 0 : 34, color: '#334155' }}>
                    <PersonOutlineIcon sx={{ fontSize: 20 }} />
                  </ListItemIcon>
                  {!isSidebarCollapsed && <ListItemText primary="Profile" primaryTypographyProps={{ fontSize: '0.9rem' }} />}
                </ListItemButton>
              </Tooltip>
            </ListItem>

            <ListItem disablePadding>
              <Tooltip title={isSidebarCollapsed ? 'Logout' : ''} placement="right">
                <ListItemButton
                  onClick={handleLogout}
                  sx={{
                    borderRadius: 2,
                    minHeight: 42,
                    justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                    px: isSidebarCollapsed ? 1 : 1.3,
                    color: '#334155',
                  }}
                >
                  <ListItemIcon sx={{ minWidth: isSidebarCollapsed ? 0 : 34, color: 'inherit' }}>
                    <LogoutIcon sx={{ fontSize: 20 }} />
                  </ListItemIcon>
                  {!isSidebarCollapsed && <ListItemText primary="Logout" primaryTypographyProps={{ fontSize: '0.9rem' }} />}
                </ListItemButton>
              </Tooltip>
            </ListItem>
          </List>
        </Box>
      )}

      <Box
        sx={{
          flexGrow: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: hideSidebar ? 'auto' : 'hidden',
        }}
      >
        <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
          <Routes>
            <Route path="/" element={<ErrorBoundary><LandingPage onLogout={handleLogout} /></ErrorBoundary>} />
            <Route path="/home" element={<Navigate to="/" replace />} />
            <Route path="/home/*" element={<Navigate to="/" replace />} />
            <Route path="/chat" element={chatRouteElement} />
            <Route path="/chat/*" element={<Navigate to="/chat" replace />} />
            <Route path="/analyze" element={analyzeRouteElement} />
            <Route path="/analyze/*" element={<Navigate to="/analyze" replace />} />
            <Route path="/cur-analysis" element={curAnalysisRouteElement} />
            <Route path="/cur-analysis/*" element={<Navigate to="/cur-analysis" replace />} />
            <Route path="/generate" element={generateRouteElement} />
            <Route path="/generate/*" element={<Navigate to="/generate" replace />} />
            <Route path="/iac" element={<Navigate to="/analyze" replace />} />
            <Route path="/iac/*" element={<Navigate to="/analyze" replace />} />
            <Route path="/settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />
            <Route path="/profile" element={<ErrorBoundary><ProfilePage /></ErrorBoundary>} />
            <Route path="/admin" element={adminRouteElement} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Box>
      </Box>
    </Box>
  );
};

const App: React.FC = () => (
  <AuthProvider>
    <AppShell />
  </AuthProvider>
);

export default App;
