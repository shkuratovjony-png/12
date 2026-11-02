FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python fix_admin_template.py && python patch_no_menu_images.py && python patch_city_chat.py && python patch_photo_profile.py && python patch_postgres_backend.py && python patch_analytics_admin_v2.py && python patch_funnel_fix.py && python patch_admin_page_safe.py && python patch_admin_credentials.py && python patch_library_backup.py && python fix_exclusive_patch.py && python patch_exclusive_matching.py && python fix_lifecycle_patch.py && python patch_lifecycle_funnel.py && python fix_lifecycle_runtime.py && python patch_priority_natal_copy.py && python patch_my_pair_browser.py && python patch_city_normalization.py && python patch_yekaterinburg_hub.py && python fix_free_communication_patch.py && python patch_free_communication_test.py && python patch_delivery_fix.py && python patch_account_reset_and_contacts.py && python fix_single_payer_patch.py && python patch_single_payer_intro.py && python patch_initiator_only_contact.py && python patch_smart_frequency_direction.py && python patch_compatibility_copy_v2.py && python patch_growth_knowledge_funnel.py && python patch_gender_neutral_onboarding.py && python -m py_compile app.py compat_knowledge.py visuals.py setup_runner.py backup_export.py backup_secure.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "setup_runner.py"]
