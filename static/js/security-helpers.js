/**
 * Security and Performance Enhancements for VPN Bot Web App
 * Provides request optimization and error handling
 */

// Enhanced fetch with error handling
async function secureFetch(url, options = {}) {
    // Set default headers
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    
    try {
        const response = await fetch(url, {
            ...options,
            headers,
            credentials: 'same-origin'  // Include cookies
        });
        
        // Handle rate limiting
        if (response.status === 429) {
            const retryAfter = response.headers.get('Retry-After') || 60;
            throw new Error(`Too many requests. Please wait ${retryAfter} seconds.`);
        }
        
        return response;
    } catch (error) {
        console.error('Fetch error:', error);
        throw error;
    }
}

// Request queue for rate limiting
const requestQueue = [];
let isProcessingQueue = false;

async function queueRequest(requestFn) {
    return new Promise((resolve, reject) => {
        requestQueue.push({ requestFn, resolve, reject });
        processQueue();
    });
}

async function processQueue() {
    if (isProcessingQueue || requestQueue.length === 0) {
        return;
    }
    
    isProcessingQueue = true;
    
    while (requestQueue.length > 0) {
        const { requestFn, resolve, reject } = requestQueue.shift();
        try {
            const result = await requestFn();
            resolve(result);
        } catch (error) {
            reject(error);
        }
        
        // Small delay between requests to prevent overwhelming server
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    
    isProcessingQueue = false;
}

// Loading state management
const loadingStates = new Map();

function showLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        loadingStates.set(elementId, element.innerHTML);
        element.innerHTML = '<div class="loading-spinner"></div>';
        element.disabled = true;
    }
}

function hideLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element && loadingStates.has(elementId)) {
        element.innerHTML = loadingStates.get(elementId);
        element.disabled = false;
        loadingStates.delete(elementId);
    }
}

// Error handling
function handleApiError(error, defaultMessage = 'خطایی رخ داد') {
    console.error('API Error:', error);
    
    let message = defaultMessage;
    
    if (error.message) {
        message = error.message;
    } else if (error.response) {
        try {
            const data = error.response.json();
            message = data.message || defaultMessage;
        } catch {
            message = defaultMessage;
        }
    }
    
    // Show user-friendly error message
    showNotification(message, 'error');
    return message;
}

// Notification system
function showNotification(message, type = 'info', duration = 5000) {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    // Add to page
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
        `;
        document.body.appendChild(container);
    }
    
    container.appendChild(notification);
    
    // Animate in
    setTimeout(() => {
        notification.style.opacity = '1';
        notification.style.transform = 'translateX(0)';
    }, 10);
    
    // Remove after duration
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(100%)';
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, duration);
}

// Cache management for client-side
const clientCache = new Map();
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

function getCached(key) {
    const cached = clientCache.get(key);
    if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
        return cached.data;
    }
    clientCache.delete(key);
    return null;
}

function setCached(key, data) {
    clientCache.set(key, {
        data,
        timestamp: Date.now()
    });
}

function clearCache(pattern = null) {
    if (pattern) {
        for (const key of clientCache.keys()) {
            if (key.includes(pattern)) {
                clientCache.delete(key);
            }
        }
    } else {
        clientCache.clear();
    }
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        secureFetch,
        showLoading,
        hideLoading,
        handleApiError,
        showNotification,
        getCached,
        setCached,
        clearCache
    };
}

