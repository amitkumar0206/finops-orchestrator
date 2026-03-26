import React, { useState } from 'react';
import { Routes, Route } from 'react-router-dom';
import { Box, AppBar, Toolbar, Chip } from '@mui/material';
import { TrendingUp as TrendingUpIcon } from '@mui/icons-material';

import ChatInterface from './components/Chat/ChatInterface';
import { ScopeIndicator } from './components/Scope';

const App: React.FC = () => {
  const [scopeVersion, setScopeVersion] = useState(0);

  const handleScopeChange = () => {
    setScopeVersion((v) => v + 1);
  };

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
            component="img"
            src="/aasmaa-logo.svg"
            alt="aasmaa"
            sx={{
              height: 40,
              mr: 3,
              filter: 'brightness(0) invert(1)',
            }}
          />
          <Box sx={{ flexGrow: 1 }}>
            <ScopeIndicator onScopeChange={handleScopeChange} />
          </Box>
          <Chip
            icon={<TrendingUpIcon sx={{ fontSize: 18 }} />}
            label="Live"
            size="small"
            sx={{
              bgcolor: 'rgba(255, 255, 255, 0.25)',
              backdropFilter: 'blur(10px)',
              color: 'white',
              fontWeight: 600,
              border: '1px solid rgba(255, 255, 255, 0.3)'
            }}
          />
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
        </Routes>
      </Box>
    </Box>
  );
};

export default App;