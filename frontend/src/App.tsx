import React, { useState } from 'react';
import { Routes, Route } from 'react-router-dom';
import { Box, AppBar, Toolbar, Typography, Chip, Avatar } from '@mui/material';
import { CloudQueue as CloudIcon, TrendingUp as TrendingUpIcon } from '@mui/icons-material';

import ChatInterface from './components/Chat/ChatInterface';
import { ScopeIndicator } from './components/Scope';

const App: React.FC = () => {
  const [scopeVersion, setScopeVersion] = useState(0);

  const handleScopeChange = () => {
    setScopeVersion((v) => v + 1);
  };

  return (
    <Box sx={{ display: 'flex', height: '100vh', bgcolor: '#f8fafc', flexDirection: 'column' }}>
      {/* Professional Header */}
      <AppBar 
        position="static" 
        elevation={0}
        sx={{ 
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.1)'
        }}
      >
        <Toolbar sx={{ py: 1 }}>
          <Avatar 
            sx={{ 
              bgcolor: 'rgba(255, 255, 255, 0.95)', 
              color: '#667eea',
              width: 40,
              height: 40,
              mr: 2
            }}
          >
            <CloudIcon />
          </Avatar>
          <Typography
            variant="h6"
            component="div"
            sx={{
              fontWeight: 700,
              letterSpacing: '-0.5px',
              color: 'white',
              mr: 3
            }}
          >
            FinOps Intelligence Platform
          </Typography>
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
      
      {/* Main content - removed padding to allow ChatInterface to use full height */}
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