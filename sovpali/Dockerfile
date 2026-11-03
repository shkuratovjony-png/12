FROM node:22-alpine AS motion-builder
WORKDIR /motion
COPY motion_site/package.json ./
RUN npm install --no-audit --no-fund
COPY motion_site/ ./
COPY coach_static/ /coach_static/
RUN node --check /coach_static/coach.js && npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=motion-builder /motion/dist /app/motion_site/dist
RUN python fix_admin_template.py && python patch_no_menu_images.py && python patch_city_chat.py && python patch_photo_profile.py && python patch_postgres_backend.py && python patch_analytics_admin_v2.py && python patch_funnel_fix.py && python patch_admin_page_safe.py && python patch_admin_credentials.py && python patch_library_backup.py && python fix_exclusive_patch.py && python patch_exclusive_matching.py && python fix_lifecycle_patch.py && python patch_lifecycle_funnel.py && python fix_lifecycle_runtime.py && python patch_priority_natal_copy.py && python patch_my_pair_browser.py && python patch_city_normalization.py && python patch_yekaterinburg_hub.py && python fix_free_communication_patch.py && python patch_free_communication_test.py && python patch_delivery_fix.py && python patch_account_reset_and_contacts.py && python fix_single_payer_patch.py && python patch_single_payer_intro.py && python patch_initiator_only_contact.py && python patch_smart_frequency_direction.py && python patch_compatibility_copy_v2.py && python patch_growth_knowledge_funnel.py && python patch_gender_neutral_onboarding.py && python patch_onboarding_7_steps.py && python patch_pair_web.py && python patch_pair_motion.py && python patch_motion_navigation.py && python patch_match_visibility.py && python patch_auto_match_recovery.py && python patch_match_push_v2.py && python patch_pair_followup.py && python patch_coach.py && python patch_site_request_flow.py && python patch_web_intro_resolution.py && python patch_ozon_billing_preview.py && python patch_ozon_web_checkout.py && python -m py_compile app.py compat_knowledge.py visuals.py pair_web.py pair_motion.py pair_conversion.py coach_web.py coach_offers.py ozon_billing_preview.py ozon_web_checkout.py web_product_access.py web_contact_checkout.py web_checkout_auth.py web_intro_fulfillment.py web_premium_checkout.py web_coach_checkout.py web_test_drive.py match_push_engine.py match_localtime.py setup_runner.py backup_export.py backup_secure.py && python test_match_visibility_build.py && python test_auto_match_recovery_build.py && python test_nationwide_matching_build.py && python test_match_push_build.py && python test_first_pair_immediate_build.py && python test_pair_followup_build.py && python test_coach_build.py && python test_site_request_build.py && python test_ozon_billing_preview_build.py && python test_ozon_web_checkout_build.py && python test_web_product_access_build.py && python test_web_contact_build.py && python test_web_checkout_auth_build.py && python test_web_premium_build.py && python test_web_coach_build.py && python test_web_test_drive_build.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "setup_runner.py"]
