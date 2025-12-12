/* =====================================
   Ultra Modern Helpers & Utilities
   ===================================== */

// Toast Notifications
function showToast(message, type = 'info') {
    // Remove existing toasts
    document.querySelectorAll('.toast-ultra').forEach(toast => toast.remove());
    
    const toast = document.createElement('div');
    toast.className = `toast-ultra toast-${type} fade-in`;
    
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    
    const colors = {
        success: '#10b981',
        error: '#ef4444',
        warning: '#f59e0b',
        info: '#667eea'
    };
    
    toast.innerHTML = `
        <div style="width: 40px; height: 40px; background: ${colors[type]}; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: white;">
            <i class="fas ${icons[type]}"></i>
        </div>
        <div style="flex: 1;">
            <div style="font-weight: 700; margin-bottom: 4px; color: var(--text-primary);">${getToastTitle(type)}</div>
            <div style="font-size: 0.875rem; color: var(--text-secondary);">${message}</div>
        </div>
        <button onclick="this.parentElement.remove()" style="background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 1.25rem;">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    document.body.appendChild(toast);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

function getToastTitle(type) {
    const titles = {
        success: 'موفقیت‌آمیز!',
        error: 'خطا!',
        warning: 'هشدار!',
        info: 'اطلاعات'
    };
    return titles[type] || 'اطلاعات';
}

@keyframes slideOutRight {
    to {
        transform: translateX(400px);
        opacity: 0;
    }
}

// Loading Toast
let loadingToast = null;

function showLoadingToast(message = 'در حال بارگذاری...') {
    hideLoadingToast();
    
    loadingToast = document.createElement('div');
    loadingToast.className = 'toast-ultra toast-info fade-in';
    loadingToast.innerHTML = `
        <div class="spinner-ultra" style="width: 40px; height: 40px;"></div>
        <div style="flex: 1;">
            <div style="font-weight: 700; color: var(--text-primary);">${message}</div>
        </div>
    `;
    
    document.body.appendChild(loadingToast);
}

function hideLoadingToast() {
    if (loadingToast) {
        loadingToast.remove();
        loadingToast = null;
    }
}

// Format Number
function formatNumber(num) {
    return new Intl.NumberFormat('fa-IR').format(num);
}

// Format Currency
function formatCurrency(amount) {
    return formatNumber(amount) + ' تومان';
}

// Format GB
function formatGB(gb) {
    return gb.toFixed(2) + ' GB';
}

// Copy to Clipboard
function copyToClipboard(text, showNotification = true) {
    navigator.clipboard.writeText(text).then(() => {
        if (showNotification) {
            showToast('کپی شد!', 'success');
        }
        return true;
    }).catch((err) => {
        if (showNotification) {
            showToast('خطا در کپی کردن', 'error');
        }
        return false;
    });
}

// Confirm Dialog
function confirmDialog(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

// Format Date
function formatDate(dateString) {
    const date = new Date(dateString);
    const options = { year: 'numeric', month: 'long', day: 'numeric' };
    return new Intl.DateTimeFormat('fa-IR', options).format(date);
}

// Calculate Days Remaining
function calculateDaysRemaining(expiryDate) {
    const now = new Date();
    const expiry = new Date(expiryDate);
    const diff = expiry - now;
    const days = Math.ceil(diff / (1000 * 60 * 60 * 24));
    return days > 0 ? days : 0;
}

// Format Time Ago
function timeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);
    
    const intervals = {
        سال: 31536000,
        ماه: 2592000,
        روز: 86400,
        ساعت: 3600,
        دقیقه: 60,
        ثانیه: 1
    };
    
    for (const [name, value] of Object.entries(intervals)) {
        const interval = Math.floor(seconds / value);
        if (interval >= 1) {
            return `${interval} ${name} پیش`;
        }
    }
    
    return 'هم‌اکنون';
}

// Debounce Function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Throttle Function
function throttle(func, limit) {
    let inThrottle;
    return function() {
        const args = arguments;
        const context = this;
        if (!inThrottle) {
            func.apply(context, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Local Storage Helpers
const storage = {
    set: (key, value) => {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.error('Error saving to localStorage', e);
            return false;
        }
    },
    
    get: (key, defaultValue = null) => {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : defaultValue;
        } catch (e) {
            console.error('Error reading from localStorage', e);
            return defaultValue;
        }
    },
    
    remove: (key) => {
        try {
            localStorage.removeItem(key);
            return true;
        } catch (e) {
            console.error('Error removing from localStorage', e);
            return false;
        }
    },
    
    clear: () => {
        try {
            localStorage.clear();
            return true;
        } catch (e) {
            console.error('Error clearing localStorage', e);
            return false;
        }
    }
};

// API Helper
async function apiCall(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    
    const mergedOptions = { ...defaultOptions, ...options };
    
    try {
        const response = await fetch(url, mergedOptions);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.message || 'خطا در ارتباط با سرور');
        }
        
        return { success: true, data };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

// Validate Input
const validators = {
    required: (value) => value && value.trim().length > 0,
    email: (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value),
    phone: (value) => /^09\d{9}$/.test(value),
    number: (value) => !isNaN(value) && value >= 0,
    minLength: (value, length) => value && value.length >= length,
    maxLength: (value, length) => value && value.length <= length,
    range: (value, min, max) => value >= min && value <= max,
};

// Initialize tooltips (if using a tooltip library)
function initTooltips() {
    document.querySelectorAll('[data-tooltip]').forEach(element => {
        element.addEventListener('mouseenter', function() {
            const tooltip = document.createElement('div');
            tooltip.className = 'tooltip-modern';
            tooltip.textContent = this.dataset.tooltip;
            tooltip.style.position = 'absolute';
            tooltip.style.top = this.offsetTop - 40 + 'px';
            tooltip.style.left = this.offsetLeft + 'px';
            document.body.appendChild(tooltip);
            this._tooltip = tooltip;
        });
        
        element.addEventListener('mouseleave', function() {
            if (this._tooltip) {
                this._tooltip.remove();
                this._tooltip = null;
            }
        });
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    initTooltips();
    
    // Add smooth scroll behavior
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        showToast,
        showLoadingToast,
        hideLoadingToast,
        formatNumber,
        formatCurrency,
        formatGB,
        copyToClipboard,
        confirmDialog,
        formatDate,
        timeAgo,
        debounce,
        throttle,
        storage,
        apiCall,
        validators
    };
}


