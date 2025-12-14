"""
Payment System for VPN Bot
Handles payment management (Gateway removed)
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# StarsefarAPI class removed as per request

class PaymentManager:
    """Manages payment operations and invoices"""
    
    def __init__(self, database_manager, starsefar_api=None):
        self.db = database_manager
        # starsefar_api is ignored/removed
        self.starsefar = None
        # Import discount manager
        try:
            from discount_manager import DiscountCodeManager
            self.discount_manager = DiscountCodeManager(database_manager)
        except ImportError:
            logger.warning("Discount manager not available")
            self.discount_manager = None
    
    def get_user_balance(self, user_id: int) -> int:
        """Get user's current balance"""
        user = self.db.get_user(user_id)
        return user.get('balance', 0) if user else 0
    
    def create_invoice(self, user_id: int, panel_id: int, gb_amount: int, amount: int, 
                     payment_method: str = 'gateway', discount_code: str = None) -> Dict[str, Any]:
        """Create a new invoice with optional discount code"""
        try:
            user = self.db.get_user(user_id)
            if not user:
                return {'success': False, 'message': 'User not found'}
            
            original_amount = amount
            discount_amount = 0
            discount_code_id = None
            
            # Apply discount code if provided
            if discount_code and self.discount_manager:
                discount_result = self.discount_manager.validate_and_apply_discount(
                    discount_code, user_id, amount
                )
                if discount_result['success']:
                    amount = discount_result['final_amount']
                    discount_amount = discount_result['discount_amount']
                    discount_code_id = discount_result['code_id']
                else:
                    # Discount code invalid, but continue without discount
                    logger.warning(f"Invalid discount code: {discount_result.get('message')}")
            
            # Create invoice in database
            invoice_id = self.db.add_invoice(
                user_id=user['id'],
                panel_id=panel_id,
                gb_amount=gb_amount,
                amount=amount,
                payment_method=payment_method,
                status='pending'
            )
            
            if not invoice_id:
                return {'success': False, 'message': 'Failed to create invoice'}
            
            # Update invoice with discount info if discount was applied
            if discount_code_id:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE invoices 
                        SET discount_code_id = ?, 
                            discount_amount = ?,
                            original_amount = ?
                        WHERE id = ?
                    ''', (discount_code_id, discount_amount, original_amount, invoice_id))
                    conn.commit()
            
            return {
                'success': True,
                'invoice_id': invoice_id,
                'amount': amount,
                'original_amount': original_amount,
                'discount_amount': discount_amount,
                'discount_applied': discount_code_id is not None
            }
            
        except Exception as e:
            logger.error(f"Error creating invoice: {e}")
            return {'success': False, 'message': str(e)}
    
    def process_balance_payment(self, user_id: int, invoice_id: int) -> Dict[str, Any]:
        """Process payment using user's balance"""
        try:
            # Get invoice
            invoice = self.db.get_invoice(invoice_id)
            if not invoice:
                return {'success': False, 'message': 'Invoice not found'}
            
            # Check if already paid
            if invoice['status'] == 'paid':
                return {'success': False, 'message': 'Invoice already paid'}
            
            # Get user
            user = self.db.get_user(user_id)
            if not user:
                return {'success': False, 'message': 'User not found'}
            
            # Use discounted amount if available
            payment_amount = invoice.get('amount', invoice.get('original_amount', 0))
            
            # Check balance
            if user['balance'] < payment_amount:
                return {'success': False, 'message': 'Insufficient balance'}
            
            # Record discount usage if discount was applied
            if invoice.get('discount_code_id') and self.discount_manager:
                discount_amount = invoice.get('discount_amount', 0)
                original_amount = invoice.get('original_amount', payment_amount + discount_amount)
                self.db.apply_discount_code(
                    code_id=invoice['discount_code_id'],
                    user_id=user['id'],
                    invoice_id=invoice_id,
                    amount_before=original_amount,
                    discount_amount=discount_amount,
                    amount_after=payment_amount
                )
            
            # Update invoice status to paid
            if not self.db.update_invoice_status(invoice_id, 'paid'):
                return {'success': False, 'message': 'Failed to update invoice'}
            
            # Deduct balance
            # Create Persian description based on purchase type
            purchase_type = invoice.get('purchase_type', 'gigabyte')
            product_id = invoice.get('product_id')
            
            if purchase_type == 'plan' and product_id:
                # Plan-based purchase
                product = self.db.get_product(product_id)
                product_name = product.get('name', '') if product else ''
                if product_name:
                    description = f'خرید اشتراک پلنی: {product_name}'
                else:
                    description = f'خرید اشتراک پلنی'
                transaction_type = 'service_purchase'
            else:
                # Gigabyte-based purchase
                description = f'خرید سرویس گیگابایتی'
                transaction_type = 'service_purchase'
            
            if not self.db.update_user_balance(user_id, -payment_amount, transaction_type, description):
                return {'success': False, 'message': 'Failed to deduct balance'}
            
            return {
                'success': True,
                'invoice_id': invoice_id,
                'amount': payment_amount,
                'discount_amount': invoice.get('discount_amount', 0)
            }
            
        except Exception as e:
            logger.error(f"Error processing balance payment: {e}")
            return {'success': False, 'message': str(e)}
    
    def process_gateway_payment(self, user_id: int, invoice_id: int) -> Dict[str, Any]:
        """Process payment through gateway (Placeholder)"""
        # Placeholder for future payment gateway
        return {'success': False, 'message': 'درگاه پرداخت غیرفعال است'}
    
    def create_balance_payment(self, user_id: int, amount: int) -> Dict[str, Any]:
        """Create a balance top-up payment (Placeholder)"""
        # Placeholder for future payment gateway
        return {'success': False, 'message': 'درگاه پرداخت غیرفعال است'}
    
    def create_service_payment(self, user_id: int, panel_id: int, volume_gb: int, price: int, 
                             invoice_id: int = None, discount_code: str = None) -> Dict[str, Any]:
        """Create a new service purchase payment (Placeholder)"""
        # Placeholder for future payment gateway
        return {'success': False, 'message': 'درگاه پرداخت غیرفعال است'}
    
    def create_volume_payment(self, user_id: int, panel_id: int, volume_gb: int, price: int, discount_code: str = None) -> Dict[str, Any]:
        """Create a volume purchase payment (Placeholder)"""
        # Placeholder for future payment gateway
        return {'success': False, 'message': 'درگاه پرداخت غیرفعال است'}
    
    def create_add_volume_payment(self, user_id: int, service_id: int, panel_id: int, volume_gb: int, price: int, discount_code: str = None) -> Dict[str, Any]:
        """Create a payment for adding volume to existing service (Placeholder)"""
        # Placeholder for future payment gateway
        return {'success': False, 'message': 'درگاه پرداخت غیرفعال است'}
