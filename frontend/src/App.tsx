import React, { useState } from 'react';
import { Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import {
  Box,
  AppBar,
  Toolbar,
  Chip,
  Button,
  IconButton,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import {
  TrendingUp as TrendingUpIcon,
  Menu as MenuIcon,
  ForumOutlined as ForumOutlinedIcon,
  InsightsOutlined as InsightsOutlinedIcon,
  AutoFixHighOutlined as AutoFixHighOutlinedIcon,
} from '@mui/icons-material';

import ChatInterface from './components/Chat/ChatInterface';
import IacWorkbenchPage from './pages/IacWorkbenchPage';
import GenerateBlueprintPage from './pages/GenerateBlueprintPage';
import { ScopeIndicator } from './components/Scope';

const App: React.FC = () => {
  const location = useLocation();
  const [scopeVersion, setScopeVersion] = useState(0);
  const [navMenuAnchor, setNavMenuAnchor] = useState<null | HTMLElement>(null);

  const handleScopeChange = () => {
    setScopeVersion((v) => v + 1);
  };

  const handleOpenNavMenu = (event: React.MouseEvent<HTMLElement>) => {
    setNavMenuAnchor(event.currentTarget);
  };

  const handleCloseNavMenu = () => {
    setNavMenuAnchor(null);
  };

  const activeRoute = (() => {
    if (location.pathname.startsWith('/generate')) return '/generate';
    if (location.pathname.startsWith('/iac') || location.pathname.startsWith('/analyze')) return '/analyze';
    return '/chat';
  })();

  return (
    <Box sx={{ display: 'flex', height: '100vh', bgcolor: '#f8fafc', flexDirection: 'column' }}>
      <AppBar
        position="static"
        elevation={0}
        sx={{
          background: 'linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.1)'
        }}
      >
        <Toolbar sx={{ py: 1 }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'rgba(255, 255, 255, 0.96)',
              borderRadius: 1.5,
              px: 1.25,
              py: 0.75,
              mr: 3,
              boxShadow: '0 2px 10px rgba(0, 0, 0, 0.12)'
            }}
          >
            <Box
              component="img"
              src="/aasmaa-logo.png"
              alt="aasmaa"
              sx={{
                width: 170,
                maxWidth: '100%',
                height: 'auto',
                objectFit: 'contain',
                display: 'block'
              }}
            />
          </Box>

          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <ScopeIndicator onScopeChange={handleScopeChange} />
          </Box>

          <Box
            sx={{
              display: { xs: 'none', md: 'flex' },
              alignItems: 'center',
              gap: 1,
              mr: 1.5,
            }}
          >
            <Button
              component={Link}
              to="/chat"
              color="inherit"
              size="small"
              startIcon={<ForumOutlinedIcon sx={{ fontSize: 16 }} />}
              sx={{
                px: 1.2,
                textTransform: 'none',
                fontWeight: 700,
                letterSpacing: 0.2,
                color: activeRoute === '/chat' ? '#ffffff' : 'rgba(255, 255, 255, 0.74)',
                borderBottom: activeRoute === '/chat' ? '2px solid #ffffff' : '2px solid transparent',
                borderRadius: 0,
                minHeight: 34,
                '& .MuiButton-startIcon': {
                  mr: 0.6,
                  ml: 0,
                },
                '&:hover': {
                  backgroundColor: 'transparent',
                  color: '#ffffff'
                }
              }}
            >
              Cost Chat
            </Button>
            <Button
              component={Link}
              to="/analyze"
              color="inherit"
              size="small"
              startIcon={<InsightsOutlinedIcon sx={{ fontSize: 16 }} />}
              sx={{
                px: 1.2,
                textTransform: 'none',
                fontWeight: 700,
                letterSpacing: 0.2,
                color: activeRoute === '/analyze' ? '#ffffff' : 'rgba(255, 255, 255, 0.74)',
                borderBottom: activeRoute === '/analyze' ? '2px solid #ffffff' : '2px solid transparent',
                borderRadius: 0,
                minHeight: 34,
                '& .MuiButton-startIcon': {
                  mr: 0.6,
                  ml: 0,
                },
                '&:hover': {
                  backgroundColor: 'transparent',
                  color: '#ffffff'
                }
              }}
            >
              Analyze
            </Button>
            <Button
              component={Link}
              to="/generate"
              color="inherit"
              size="small"
              startIcon={<AutoFixHighOutlinedIcon sx={{ fontSize: 16 }} />}
              sx={{
                px: 1.2,
                textTransform: 'none',
                fontWeight: 700,
                letterSpacing: 0.2,
                color: activeRoute === '/generate' ? '#ffffff' : 'rgba(255, 255, 255, 0.74)',
                borderBottom: activeRoute === '/generate' ? '2px solid #ffffff' : '2px solid transparent',
                borderRadius: 0,
                minHeight: 34,
                '& .MuiButton-startIcon': {
                  mr: 0.6,
                  ml: 0,
                },
                '&:hover': {
                  backgroundColor: 'transparent',
                  color: '#ffffff'
                }
              }}
            >
              Generate
            </Button>
          </Box>

          <Chip
            icon={<TrendingUpIcon sx={{ fontSize: 18, color: '#22c55e !important' }} />}
            label="Live"
            size="small"
            sx={{
              bgcolor: 'rgba(16, 185, 129, 0.18)',
              backdropFilter: 'blur(10px)',
              color: 'white',
              fontWeight: 600,
              border: '1px solid rgba(34, 197, 94, 0.55)',
              mr: { xs: 1, md: 2 }
            }}
          />

          <IconButton
            color="inherit"
            onClick={handleOpenNavMenu}
            sx={{
              display: { xs: 'inline-flex', md: 'none' },
              mr: 0.5,
              border: '1px solid rgba(255, 255, 255, 0.25)',
              backgroundColor: 'rgba(255, 255, 255, 0.08)'
            }}
          >
            <MenuIcon />
          </IconButton>

          <Menu
            anchorEl={navMenuAnchor}
            open={Boolean(navMenuAnchor)}
            onClose={handleCloseNavMenu}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            transformOrigin={{ vertical: 'top', horizontal: 'right' }}
            PaperProps={{
              sx: {
                mt: 1,
                minWidth: 220,
                borderRadius: 2,
                border: '1px solid rgba(15, 23, 42, 0.08)'
              }
            }}
          >
            <MenuItem
              component={Link}
              to="/chat"
              onClick={handleCloseNavMenu}
              selected={activeRoute === '/chat'}
            >
              <ListItemIcon sx={{ minWidth: 30 }}>
                <ForumOutlinedIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText primary="Cost Chat" />
            </MenuItem>
            <MenuItem
              component={Link}
              to="/analyze"
              onClick={handleCloseNavMenu}
              selected={activeRoute === '/analyze'}
            >
              <ListItemIcon sx={{ minWidth: 30 }}>
                <InsightsOutlinedIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText primary="Analyze" />
            </MenuItem>
            <MenuItem
              component={Link}
              to="/generate"
              onClick={handleCloseNavMenu}
              selected={activeRoute === '/generate'}
            >
              <ListItemIcon sx={{ minWidth: 30 }}>
                <AutoFixHighOutlinedIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText primary="Generate" />
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      <Box
        sx={{
          flexGrow: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden'
        }}
      >
        <Routes>
          <Route path="/" element={<ChatInterface key={scopeVersion} />} />
          <Route path="/chat" element={<ChatInterface key={scopeVersion} />} />
          <Route path="/chat/*" element={<Navigate to="/chat" replace />} />
          <Route path="/analyze" element={<IacWorkbenchPage />} />
          <Route path="/analyze/*" element={<Navigate to="/analyze" replace />} />
          <Route path="/generate" element={<GenerateBlueprintPage />} />
          <Route path="/generate/*" element={<Navigate to="/generate" replace />} />
          <Route path="/iac" element={<Navigate to="/analyze" replace />} />
          <Route path="/iac/*" element={<Navigate to="/analyze" replace />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </Box>
    </Box>
  );
};
export default App;