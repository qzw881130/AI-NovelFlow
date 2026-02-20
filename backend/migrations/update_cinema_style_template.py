#!/usr/bin/env python3
"""
Migration: Update "电影风格分镜" (System Default) template to match "电影风格分镜 (副本)"
Date: 2026-02-20

This script updates the system default cinema style prompt template to include
enhanced "台词零丢失硬约束" (100% dialogue preservation rules).

Key improvements:
1. 【台词零丢失硬约束】- Ensures 100% of original dialogue is preserved
2. Quotes extraction step (quotes array) for internal validation
3. Complete self-check mechanism to verify no dialogue is lost
4. Strict speaker mapping rules (no generic terms like "众人/人群")
5. video_description length: 90-220 characters (increased from 90-180)
"""

import sys
sys.path.insert(0, '..')

from app.core.database import SessionLocal
from app.models.prompt_template import PromptTemplate


def migrate():
    db = SessionLocal()
    try:
        # Get the copy template
        copy_template = db.query(PromptTemplate).filter(
            PromptTemplate.name == '电影风格分镜 (副本)'
        ).first()
        
        if not copy_template:
            print("❌ Error: '电影风格分镜 (副本)' template not found")
            return False
        
        # Get the system default template
        system_template = db.query(PromptTemplate).filter(
            PromptTemplate.name == '电影风格分镜',
            PromptTemplate.is_system == True
        ).first()
        
        if not system_template:
            print("❌ Error: '电影风格分镜' (system default) template not found")
            return False
        
        print(f"📋 Current state:")
        print(f"   System template length: {len(system_template.template)} chars")
        print(f"   Copy template length: {len(copy_template.template)} chars")
        
        # Update system template with copy's content
        system_template.template = copy_template.template
        db.commit()
        
        # Verify
        db.refresh(system_template)
        print(f"\n✅ Migration successful!")
        print(f"   Updated system template length: {len(system_template.template)} chars")
        
        if system_template.template == copy_template.template:
            print("   Templates are now identical ✓")
        else:
            print("   ⚠ Warning: Templates still differ")
            
        return True
        
    except Exception as e:
        db.rollback()
        print(f"❌ Migration failed: {e}")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
