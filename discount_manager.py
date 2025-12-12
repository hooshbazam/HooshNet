"""
Advanced Discount and Gift Code Management System
Handles discount codes and gift codes with comprehensive validation and application
"""

import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from professional_database import ProfessionalDatabaseManager

logger = logging.getLogger(__name__)

class DiscountCodeManager:
    """Manages discount codes and gift codes"""
    
    def __init__(self, db: ProfessionalDatabaseManager):
        self.db = db
    
    def calculate_discount(self, discount_code: Dict, amount: int) -> Tuple[int, int]:
        """
        Calculate discount amount based on discount code
        
        Returns:
            Tuple[discount_amount, final_amount]
        """
        discount_type = discount_code['discount_type']
        discount_value = discount_code['discount_value']
        
        if discount_type == 'percentage':
            discount_amount = int((amount * discount_value) / 100)
            # Apply max discount limit if exists
            if discount_code['max_discount_amount']:
                discount_amount = min(discount_amount, discount_code['max_discount_amount'])
        elif discount_type == 'fixed':
            discount_amount = int(discount_value)
            # Can't discount more than the amount
            discount_amount = min(discount_amount, amount)
        else:
            discount_amount = 0
        
        final_amount = max(0, amount - discount_amount)
        return discount_amount, final_amount
    
    def validate_and_apply_discount(self, code: str, user_id: int, amount: int) -> Dict:
        """
        Validate discount code and return discount details
        
        Returns:
            Dict with success status, message, discount_amount, final_amount, and code details
        """
        # Get user database ID
        user = self.db.get_user(user_id)
        if not user:
            return {
                'success': False,
                'message': 'کاربر یافت نشد'
            }
        
        db_user_id = user['id']
        
        # Validate discount code
        is_valid, error_message, discount_code = self.db.validate_discount_code(code, db_user_id, amount)
        
        if not is_valid:
            return {
                'success': False,
                'message': error_message
            }
        
        # Calculate discount
        discount_amount, final_amount = self.calculate_discount(discount_code, amount)
        
        return {
            'success': True,
            'message': f'کد تخفیف اعمال شد! تخفیف: {discount_amount:,} تومان',
            'discount_amount': discount_amount,
            'final_amount': final_amount,
            'original_amount': amount,
            'code_id': discount_code['id'],
            'code': discount_code['code'],
            'discount_code': discount_code
        }
    
    def apply_discount_to_invoice(self, code: str, user_id: int, invoice_id: int, amount: int) -> Dict:
        """
        Apply discount code to an invoice
        
        Returns:
            Dict with success status and updated invoice details
        """
        # Validate discount
        validation_result = self.validate_and_apply_discount(code, user_id, amount)
        
        if not validation_result['success']:
            return validation_result
        
        # Get user database ID
        user = self.db.get_user(user_id)
        db_user_id = user['id']
        
        # Record discount usage
        success = self.db.apply_discount_code(
            code_id=validation_result['code_id'],
            user_id=db_user_id,
            invoice_id=invoice_id,
            amount_before=amount,
            discount_amount=validation_result['discount_amount'],
            amount_after=validation_result['final_amount']
        )
        
        if not success:
            return {
                'success': False,
                'message': 'خطا در ثبت استفاده از کد تخفیف'
            }
        
        # Update invoice with discount
        invoice = self.db.get_invoice(invoice_id)
        if invoice:
            # Update invoice amount
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE invoices 
                    SET discount_code_id = ?, 
                        discount_amount = ?,
                        original_amount = ?,
                        amount = ?
                    WHERE id = ?
                ''', (validation_result['code_id'], 
                      validation_result['discount_amount'],
                      amount,
                      validation_result['final_amount'],
                      invoice_id))
                conn.commit()
        
        return validation_result
    
    def validate_and_apply_gift_code(self, code: str, user_id: int) -> Dict:
        """
        Validate and apply gift code to user balance
        
        Returns:
            Dict with success status and gift amount
        """
        # Get user database ID
        user = self.db.get_user(user_id)
        if not user:
            return {
                'success': False,
                'message': 'کاربر یافت نشد'
            }
        
        db_user_id = user['id']
        
        # Validate gift code
        is_valid, error_message, gift_code = self.db.validate_gift_code(code, db_user_id)
        
        if not is_valid:
            return {
                'success': False,
                'message': error_message
            }
        
        # Apply gift code
        success = self.db.apply_gift_code(gift_code['id'], db_user_id, gift_code['amount'])
        
        if not success:
            return {
                'success': False,
                'message': 'خطا در اعمال کد هدیه'
            }
        
        return {
            'success': True,
            'message': f'کد هدیه با موفقیت اعمال شد! {gift_code["amount"]:,} تومان به حساب شما اضافه شد.',
            'amount': gift_code['amount'],
            'code': gift_code['code']
        }
    
    def get_active_discount_codes(self) -> list:
        """Get all active discount codes"""
        return self.db.get_all_discount_codes(active_only=True)
    
    def get_active_gift_codes(self) -> list:
        """Get all active gift codes"""
        return self.db.get_all_gift_codes(active_only=True)


class DiscountCodeAdmin:
    """Admin functions for managing discount and gift codes"""
    
    def __init__(self, db: ProfessionalDatabaseManager):
        self.db = db
    
    def create_discount_code(self, code: str, discount_type: str, discount_value: float,
                            max_discount_amount: Optional[int] = None,
                            min_purchase_amount: int = 0,
                            max_uses: int = 0,
                            valid_from: Optional[datetime] = None,
                            valid_until: Optional[datetime] = None,
                            applicable_to: str = 'all',
                            created_by: Optional[int] = None,
                            description: Optional[str] = None,
                            notes: Optional[str] = None) -> Tuple[bool, str]:
        """
        Create a new discount code
        
        Returns:
            Tuple[success, message]
        """
        try:
            # Check if code already exists
            existing = self.db.get_discount_code(code)
            if existing:
                return False, f"کد تخفیف '{code}' از قبل وجود دارد"
            
            code_id = self.db.create_discount_code(
                code=code,
                discount_type=discount_type,
                discount_value=discount_value,
                max_discount_amount=max_discount_amount,
                min_purchase_amount=min_purchase_amount,
                max_uses=max_uses,
                valid_from=valid_from,
                valid_until=valid_until,
                applicable_to=applicable_to,
                created_by=created_by,
                description=description,
                notes=notes
            )
            
            if code_id:
                return True, f"کد تخفیف '{code}' با موفقیت ایجاد شد"
            else:
                return False, "خطا در ایجاد کد تخفیف"
                
        except Exception as e:
            logger.error(f"Error creating discount code: {e}")
            return False, f"خطا در ایجاد کد تخفیف: {str(e)}"
    
    def create_gift_code(self, code: str, amount: int,
                        max_uses: int = 1,
                        valid_from: Optional[datetime] = None,
                        valid_until: Optional[datetime] = None,
                        created_by: Optional[int] = None,
                        description: Optional[str] = None,
                        notes: Optional[str] = None) -> Tuple[bool, str]:
        """
        Create a new gift code
        
        Returns:
            Tuple[success, message]
        """
        try:
            # Check if code already exists
            existing = self.db.get_gift_code(code)
            if existing:
                return False, f"کد هدیه '{code}' از قبل وجود دارد"
            
            code_id = self.db.create_gift_code(
                code=code,
                amount=amount,
                max_uses=max_uses,
                valid_from=valid_from,
                valid_until=valid_until,
                created_by=created_by,
                description=description,
                notes=notes
            )
            
            if code_id:
                return True, f"کد هدیه '{code}' با موفقیت ایجاد شد"
            else:
                return False, "خطا در ایجاد کد هدیه"
                
        except Exception as e:
            logger.error(f"Error creating gift code: {e}")
            return False, f"خطا در ایجاد کد هدیه: {str(e)}"
    
    def update_discount_code(self, code_id: int, **kwargs) -> Tuple[bool, str]:
        """Update discount code"""
        try:
            success = self.db.update_discount_code(code_id, **kwargs)
            if success:
                return True, "کد تخفیف با موفقیت بروزرسانی شد"
            else:
                return False, "خطا در بروزرسانی کد تخفیف"
        except Exception as e:
            logger.error(f"Error updating discount code: {e}")
            return False, f"خطا در بروزرسانی کد تخفیف: {str(e)}"
    
    def delete_discount_code(self, code_id: int) -> Tuple[bool, str]:
        """Delete discount code"""
        try:
            success = self.db.delete_discount_code(code_id)
            if success:
                return True, "کد تخفیف با موفقیت حذف شد"
            else:
                return False, "خطا در حذف کد تخفیف"
        except Exception as e:
            logger.error(f"Error deleting discount code: {e}")
            return False, f"خطا در حذف کد تخفیف: {str(e)}"
    
    def get_all_discount_codes(self) -> list:
        """Get all discount codes"""
        return self.db.get_all_discount_codes(active_only=False)
    
    def get_all_gift_codes(self) -> list:
        """Get all gift codes"""
        return self.db.get_all_gift_codes(active_only=False)
    
    def get_discount_code_stats(self, code_id: int) -> Dict:
        """Get statistics for a discount code"""
        return self.db.get_discount_code_statistics(code_id)
    
    def get_gift_code_stats(self, code_id: int) -> Dict:
        """Get statistics for a gift code"""
        return self.db.get_gift_code_statistics(code_id)













