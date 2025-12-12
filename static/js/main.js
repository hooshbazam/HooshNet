/**
 * VPN Panel - Main JavaScript
 * Professional, Modern, Interactive
 */

// =====================================
// Theme Management
// =====================================

const themeToggle = document.getElementById('themeToggle');
const body = document.body;

// Load saved theme
const savedTheme = localStorage.getItem('theme') || 'light';
body.setAttribute('data-theme', savedTheme);

// Theme toggle handler
if (themeToggle) {
    themeToggle.addEventListener('click', () => {
        const currentTheme = body.getAttribute('data-theme');
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        
        body.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        
        // Add animation
        themeToggle.style.transform = 'rotate(360deg)';
        setTimeout(() => {
            themeToggle.style.transform = 'rotate(0deg)';
        }, 300);
    });
}

// =====================================
// Sidebar Management
// =====================================

const sidebarToggle = document.getElementById('sidebarToggle');
const mobileToggle = document.getElementById('mobileToggle');
const sidebar = document.getElementById('sidebar');
const mainContent = document.getElementById('mainContent');

if (mobileToggle && sidebar) {
    mobileToggle.addEventListener('click', () => {
        sidebar.classList.toggle('show');
        
        // Close sidebar when clicking outside on mobile
        if (sidebar.classList.contains('show')) {
            document.addEventListener('click', closeSidebarOnClickOutside);
        }
    });
}

function closeSidebarOnClickOutside(e) {
    if (sidebar && !sidebar.contains(e.target) && !mobileToggle.contains(e.target)) {
        sidebar.classList.remove('show');
        document.removeEventListener('click', closeSidebarOnClickOutside);
    }
}

// =====================================
// User Dropdown Menu
// =====================================

const userMenuToggle = document.getElementById('userMenuToggle');
const userDropdown = document.getElementById('userDropdown');

if (userMenuToggle && userDropdown) {
    userMenuToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        userDropdown.classList.toggle('show');
    });
    
    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!userMenuToggle.contains(e.target) && !userDropdown.contains(e.target)) {
            userDropdown.classList.remove('show');
        }
    });
}

// =====================================
// Toast Notifications
// =====================================

function showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    
    const iconMap = {
        success: 'check-circle',
        error: 'exclamation-circle',
        warning: 'exclamation-triangle',
        info: 'info-circle'
    };
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <i class="fas fa-${iconMap[type] || 'info-circle'}"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => {
        toast.classList.add('toast-show');
    }, 10);
    
    // Auto remove
    setTimeout(() => {
        toast.classList.remove('toast-show');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, duration);
}

// Make showToast globally available
window.showToast = showToast;

// =====================================
// Smooth Scroll
// =====================================

document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        if (href !== '#' && document.querySelector(href)) {
            e.preventDefault();
            document.querySelector(href).scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// =====================================
// Loading States
// =====================================

function setButtonLoading(button, loading = true) {
    if (loading) {
        button.dataset.originalText = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> در حال بارگذاری...';
    } else {
        button.disabled = false;
        button.innerHTML = button.dataset.originalText || button.innerHTML;
    }
}

window.setButtonLoading = setButtonLoading;

// =====================================
// Form Validation
// =====================================

function validateForm(formElement) {
    const inputs = formElement.querySelectorAll('input[required], textarea[required], select[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            isValid = false;
            input.classList.add('error');
            
            // Remove error class on input
            input.addEventListener('input', function() {
                this.classList.remove('error');
            }, { once: true });
        }
    });
    
    return isValid;
}

window.validateForm = validateForm;

// =====================================
// Copy to Clipboard
// =====================================

function copyToClipboard(text, successMessage = 'کپی شد!') {
    // Modern Clipboard API
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showToast(successMessage, 'success');
        }).catch(err => {
            // Fallback to older method
            fallbackCopyToClipboard(text, successMessage);
        });
    } else {
        fallbackCopyToClipboard(text, successMessage);
    }
}

function fallbackCopyToClipboard(text, successMessage) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.top = '-9999px';
    textArea.style.left = '-9999px';
    document.body.appendChild(textArea);
    textArea.select();
    
    try {
        document.execCommand('copy');
        showToast(successMessage, 'success');
    } catch (err) {
        showToast('خطا در کپی کردن', 'error');
    }
    
    document.body.removeChild(textArea);
}

window.copyToClipboard = copyToClipboard;

// =====================================
// Number Formatting (Persian)
// =====================================

function formatNumber(num) {
    return new Intl.NumberFormat('fa-IR').format(num);
}

window.formatNumber = formatNumber;

// =====================================
// Auto-update Relative Times
// =====================================

function updateRelativeTimes() {
    document.querySelectorAll('[data-time]').forEach(element => {
        const timestamp = parseInt(element.dataset.time);
        if (timestamp) {
            element.textContent = getRelativeTime(timestamp);
        }
    });
}

function getRelativeTime(timestamp) {
    const now = Date.now();
    const diff = now - timestamp;
    
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    
    if (days > 0) return `${days} روز پیش`;
    if (hours > 0) return `${hours} ساعت پیش`;
    if (minutes > 0) return `${minutes} دقیقه پیش`;
    return 'چند لحظه پیش';
}

// Update relative times every minute
setInterval(updateRelativeTimes, 60000);
updateRelativeTimes();

// =====================================
// Lazy Loading Images
// =====================================

if ('IntersectionObserver' in window) {
    const imageObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src;
                img.classList.remove('lazy');
                imageObserver.unobserve(img);
            }
        });
    });
    
    document.querySelectorAll('img.lazy').forEach(img => {
        imageObserver.observe(img);
    });
}

// =====================================
// Progress Bars Animation
// =====================================

function animateProgressBars() {
    const progressBars = document.querySelectorAll('.progress-fill, .usage-fill, .traffic-fill');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const bar = entry.target;
                const width = bar.style.width;
                bar.style.width = '0%';
                
                setTimeout(() => {
                    bar.style.width = width;
                }, 100);
                
                observer.unobserve(bar);
            }
        });
    }, { threshold: 0.1 });
    
    progressBars.forEach(bar => observer.observe(bar));
}

// Run on page load
document.addEventListener('DOMContentLoaded', animateProgressBars);

// =====================================
// Confetti Animation (for success actions)
// =====================================

function confetti() {
    const colors = ['#6366f1', '#8b5cf6', '#10b981', '#f59e0b'];
    const confettiCount = 50;
    const container = document.body;
    
    for (let i = 0; i < confettiCount; i++) {
        const confetti = document.createElement('div');
        confetti.style.cssText = `
            position: fixed;
            width: 10px;
            height: 10px;
            background-color: ${colors[Math.floor(Math.random() * colors.length)]};
            left: ${Math.random() * 100}%;
            top: -10px;
            opacity: 1;
            transform: rotate(${Math.random() * 360}deg);
            pointer-events: none;
            z-index: 99999;
            border-radius: 2px;
        `;
        
        container.appendChild(confetti);
        
        const animation = confetti.animate([
            {
                transform: `translateY(0) rotate(0deg)`,
                opacity: 1
            },
            {
                transform: `translateY(${window.innerHeight + 20}px) rotate(${Math.random() * 720}deg)`,
                opacity: 0
            }
        ], {
            duration: 2000 + Math.random() * 1000,
            easing: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)'
        });
        
        animation.onfinish = () => confetti.remove();
    }
}

window.confetti = confetti;

// =====================================
// Keyboard Shortcuts
// =====================================

document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd + K for search (if search exists)
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[type="search"]');
        if (searchInput) {
            searchInput.focus();
        }
    }
    
    // ESC to close modals
    if (e.key === 'Escape') {
        const openModals = document.querySelectorAll('.modal.modal-show');
        openModals.forEach(modal => {
            modal.classList.remove('modal-show');
        });
        
        const openDropdowns = document.querySelectorAll('.user-dropdown.show');
        openDropdowns.forEach(dropdown => {
            dropdown.classList.remove('show');
        });
    }
});

// =====================================
// Auto-save Form Data
// =====================================

function enableAutoSave(formElement, key) {
    const inputs = formElement.querySelectorAll('input, textarea, select');
    
    // Load saved data
    const saved = localStorage.getItem(key);
    if (saved) {
        try {
            const data = JSON.parse(saved);
            inputs.forEach(input => {
                if (data[input.name]) {
                    input.value = data[input.name];
                }
            });
        } catch (e) {
            console.error('Error loading saved form data:', e);
        }
    }
    
    // Save on change
    inputs.forEach(input => {
        input.addEventListener('change', () => {
            const data = {};
            inputs.forEach(inp => {
                data[inp.name] = inp.value;
            });
            localStorage.setItem(key, JSON.stringify(data));
        });
    });
    
    // Clear on submit
    formElement.addEventListener('submit', () => {
        localStorage.removeItem(key);
    });
}

window.enableAutoSave = enableAutoSave;

// =====================================
// Animated Numbers (Count Up)
// =====================================

function animateValue(element, start, end, duration) {
    const range = end - start;
    const increment = range / (duration / 16);
    let current = start;
    
    const timer = setInterval(() => {
        current += increment;
        if ((increment > 0 && current >= end) || (increment < 0 && current <= end)) {
            current = end;
            clearInterval(timer);
        }
        element.textContent = Math.floor(current).toLocaleString('fa-IR');
    }, 16);
}

// Animate stat numbers on page load
document.addEventListener('DOMContentLoaded', () => {
    const statValues = document.querySelectorAll('.stat-value[data-value]');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const element = entry.target;
                const endValue = parseInt(element.dataset.value);
                animateValue(element, 0, endValue, 1000);
                observer.unobserve(element);
            }
        });
    }, { threshold: 0.1 });
    
    statValues.forEach(stat => observer.observe(stat));
});

// =====================================
// Print Functionality
// =====================================

function printElement(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    const printWindow = window.open('', '_blank');
    printWindow.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Print</title>
            <link rel="stylesheet" href="/static/css/style.css">
            <style>
                body { margin: 20px; }
                @media print {
                    .no-print { display: none !important; }
                }
            </style>
        </head>
        <body>
            ${element.innerHTML}
        </body>
        </html>
    `);
    printWindow.document.close();
    printWindow.focus();
    setTimeout(() => {
        printWindow.print();
        printWindow.close();
    }, 250);
}

window.printElement = printElement;

// =====================================
// Network Status Indicator
// =====================================

window.addEventListener('online', () => {
    showToast('اتصال اینترنت برقرار شد', 'success');
});

window.addEventListener('offline', () => {
    showToast('اتصال اینترنت قطع شد', 'error');
});

// =====================================
// Performance Monitoring
// =====================================

if ('PerformanceObserver' in window) {
    try {
        const perfObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                if (entry.duration > 1000) {
                    console.warn(`Slow operation detected: ${entry.name} took ${entry.duration}ms`);
                }
            }
        });
        
        perfObserver.observe({ entryTypes: ['measure'] });
    } catch (e) {
        // PerformanceObserver not fully supported
    }
}

// =====================================
// Accessibility Improvements
// =====================================

// Add skip to main content link
document.addEventListener('DOMContentLoaded', () => {
    const skipLink = document.createElement('a');
    skipLink.href = '#main';
    skipLink.textContent = 'پرش به محتوای اصلی';
    skipLink.className = 'skip-link';
    skipLink.style.cssText = `
        position: absolute;
        left: -9999px;
        z-index: 999;
        padding: 1em;
        background-color: var(--primary-color);
        color: white;
        text-decoration: none;
    `;
    skipLink.addEventListener('focus', () => {
        skipLink.style.left = '0';
    });
    skipLink.addEventListener('blur', () => {
        skipLink.style.left = '-9999px';
    });
    
    document.body.insertBefore(skipLink, document.body.firstChild);
});

// =====================================
// Console Welcome Message
// =====================================

console.log(`
%c
╔══════════════════════════════════════╗
║   VPN Panel - Professional Edition   ║
║   Version 1.0.0                      ║
╚══════════════════════════════════════╝
%c
`, 'color: #6366f1; font-size: 14px; font-weight: bold;', '');

// =====================================
// Error Handling
// =====================================

window.addEventListener('error', (event) => {
    console.error('Global error:', event.error);
    // You can send errors to a logging service here
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
    // You can send errors to a logging service here
});

console.log('✅ VPN Panel JavaScript loaded successfully');


