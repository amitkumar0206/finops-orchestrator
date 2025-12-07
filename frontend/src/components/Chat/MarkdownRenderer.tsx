import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Box, Typography, IconButton, Tooltip } from '@mui/material';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';

interface MarkdownRendererProps {
  content: string;
}

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content }) => {
  const [tableHoverIndex, setTableHoverIndex] = useState<number | null>(null);

  const openTableInNewTab = (tableContent: string) => {
    const htmlContent = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>Cost Analysis Table</title>
          <style>
            body {
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
              margin: 20px;
              background: #f8fafc;
            }
            table {
              width: 100%;
              border-collapse: collapse;
              background: white;
              box-shadow: 0 2px 8px rgba(0,0,0,0.1);
              border-radius: 8px;
              overflow: hidden;
            }
            th {
              background: rgba(102, 126, 234, 0.1);
              padding: 12px;
              text-align: left;
              font-weight: 600;
              border-bottom: 2px solid rgba(102, 126, 234, 0.3);
              white-space: nowrap;
            }
            td {
              padding: 12px;
              border-bottom: 1px solid rgba(0,0,0,0.05);
              text-align: right;
            }
            td:first-child {
              text-align: left;
              font-weight: 500;
            }
            tr:last-child td {
              border-bottom: none;
            }
            tr:hover {
              background: rgba(102, 126, 234, 0.05);
            }
          </style>
        </head>
        <body>
          ${tableContent}
        </body>
      </html>
    `;
    const blob = new Blob([htmlContent], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 100);
  };

  let tableIndex = -1;

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Headings
        h1: ({ children }) => (
          <Typography
            variant="h4"
            sx={{
              fontWeight: 700,
              mb: 2,
              mt: 3,
              color: '#667eea',
              borderBottom: '2px solid #667eea',
              pb: 1
            }}
          >
            {children}
          </Typography>
        ),
        h2: ({ children }) => (
          <Typography
            variant="h5"
            sx={{
              fontWeight: 600,
              mb: 1.5,
              mt: 2.5,
              color: '#667eea'
            }}
          >
            {children}
          </Typography>
        ),
        h3: ({ children }) => (
          <Typography
            variant="h6"
            sx={{
              fontWeight: 600,
              mb: 1,
              mt: 2,
              color: '#667eea'
            }}
          >
            {children}
          </Typography>
        ),
        
        // Paragraphs
        p: ({ children }) => (
          <Typography
            variant="body1"
            sx={{
              mb: 1,
              lineHeight: 1.6,
              fontSize: '0.95rem',
              color: 'text.primary',
              '&:last-child': {
                mb: 0
              }
            }}
          >
            {children}
          </Typography>
        ),
        
        // Strong (bold)
        strong: ({ children }) => (
          <Box
            component="span"
            sx={{
              fontWeight: 700,
              color: '#1a1a1a'
            }}
          >
            {children}
          </Box>
        ),
        
        // Emphasis (italic)
        em: ({ children }) => (
          <Box
            component="span"
            sx={{
              fontStyle: 'italic',
              color: '#4a5568'
            }}
          >
            {children}
          </Box>
        ),
        
        // Lists
        ul: ({ children }) => (
          <Box
            component="ul"
            sx={{
              pl: 3,
              mb: 1.5,
              '& li': {
                mb: 0.5,
                lineHeight: 1.5
              }
            }}
          >
            {children}
          </Box>
        ),
        ol: ({ children }) => (
          <Box
            component="ol"
            sx={{
              pl: 3,
              mb: 1.5,
              '& li': {
                mb: 0.5,
                lineHeight: 1.5
              }
            }}
          >
            {children}
          </Box>
        ),
        li: ({ children }) => (
          <Typography
            component="li"
            sx={{
              fontSize: '0.95rem',
              color: 'text.primary',
              '&:last-child': {
                mb: 0
              }
            }}
          >
            {children}
          </Typography>
        ),
        
        // Code blocks
        code: ({ inline, children }: any) => {
          if (inline) {
            return (
              <Box
                component="code"
                sx={{
                  bgcolor: 'rgba(102, 126, 234, 0.1)',
                  color: '#667eea',
                  px: 0.75,
                  py: 0.25,
                  borderRadius: 1,
                  fontSize: '0.875rem',
                  fontFamily: 'monospace'
                }}
              >
                {children}
              </Box>
            );
          }
          
          return (
            <Box
              component="pre"
              sx={{
                bgcolor: '#f5f5f5',
                p: 2,
                borderRadius: 2,
                overflow: 'auto',
                mb: 2,
                border: '1px solid rgba(0,0,0,0.1)'
              }}
            >
              <Box
                component="code"
                sx={{
                  fontSize: '0.875rem',
                  fontFamily: 'monospace',
                  color: '#1a1a1a'
                }}
              >
                {children}
              </Box>
            </Box>
          );
        },
        
        // Tables
        table: ({ children }: any) => {
          tableIndex++;
          const currentIndex = tableIndex;
          
          return (
            <Box
              sx={{
                position: 'relative',
                mb: 2,
              }}
              onMouseEnter={() => setTableHoverIndex(currentIndex)}
              onMouseLeave={() => setTableHoverIndex(null)}
            >
              {tableHoverIndex === currentIndex && (
                <Box
                  sx={{
                    position: 'absolute',
                    top: 8,
                    right: 8,
                    zIndex: 10,
                  }}
                >
                  <Tooltip title="Open table in new tab">
                    <IconButton
                      size="small"
                      onClick={() => {
                        // Reconstruct table from children
                        const tableElement = document.querySelectorAll('table')[currentIndex];
                        if (tableElement) {
                          openTableInNewTab(tableElement.outerHTML);
                        }
                      }}
                      sx={{
                        bgcolor: 'white',
                        boxShadow: 2,
                        '&:hover': {
                          bgcolor: 'rgba(102, 126, 234, 0.1)',
                        },
                      }}
                    >
                      <OpenInNewIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </Box>
              )}
              <Box
                sx={{
                  overflowX: 'auto',
                  border: '1px solid rgba(0,0,0,0.1)',
                  borderRadius: 2,
                  maxWidth: '100%',
                  '&::-webkit-scrollbar': {
                    height: '8px',
                  },
                  '&::-webkit-scrollbar-track': {
                    background: 'rgba(0,0,0,0.05)',
                    borderRadius: '10px',
                  },
                  '&::-webkit-scrollbar-thumb': {
                    background: 'rgba(0,0,0,0.2)',
                    borderRadius: '10px',
                    '&:hover': {
                      background: 'rgba(0,0,0,0.3)',
                    },
                  },
                }}
              >
                <Box
                  component="table"
                  sx={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    minWidth: '600px', // Ensure table has minimum width for scrolling
                    '& th': {
                      bgcolor: 'rgba(102, 126, 234, 0.1)',
                      p: 1.5,
                      textAlign: 'left',
                      fontWeight: 600,
                      borderBottom: '2px solid rgba(102, 126, 234, 0.3)',
                      whiteSpace: 'nowrap',
                      position: 'sticky',
                      top: 0,
                      zIndex: 3,
                      boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
                    },
                    '& td': {
                      p: 1.5,
                      borderBottom: '1px solid rgba(0,0,0,0.05)',
                      textAlign: 'right',
                      whiteSpace: 'nowrap',
                    },
                    '& td:first-of-type': {
                      textAlign: 'left',
                      fontWeight: 500,
                      position: 'sticky',
                      left: 0,
                      bgcolor: 'white',
                      zIndex: 1,
                      maxWidth: '200px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    },
                    '& th:first-of-type': {
                      position: 'sticky',
                      left: 0,
                      zIndex: 4,
                      bgcolor: 'rgba(102, 126, 234, 0.1)',
                      maxWidth: '200px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      boxShadow: '2px 0 4px rgba(0,0,0,0.1)',
                    },
                    '& tr:last-child td': {
                      borderBottom: 'none'
                    },
                    '& tr:hover': {
                      bgcolor: 'rgba(102, 126, 234, 0.05)',
                    },
                  }}
                >
                  {children}
                </Box>
              </Box>
            </Box>
          );
        },
        
        // Horizontal rule
        hr: () => (
          <Box
            sx={{
              height: '1px',
              bgcolor: 'rgba(0,0,0,0.1)',
              my: 3
            }}
          />
        ),
        
        // Blockquotes
        blockquote: ({ children }) => (
          <Box
            sx={{
              borderLeft: '4px solid #667eea',
              pl: 2,
              py: 1,
              my: 2,
              bgcolor: 'rgba(102, 126, 234, 0.05)',
              fontStyle: 'italic',
              color: '#4a5568'
            }}
          >
            {children}
          </Box>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
};

export default MarkdownRenderer;
